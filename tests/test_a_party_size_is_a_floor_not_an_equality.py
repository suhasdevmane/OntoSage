# -*- coding: utf-8 -*-
"""A size asked for is a MINIMUM, and the arithmetic is done in code (BUG-1399).

THE DEFECT, live, facility01 on /v1, `resp_cache:*` flushed:

    Q  "Find a room for 12 with a projector, free 2-4pm today, near the cafe."
    A  "| Rooms that can seat 12 people | 0 |
        | Rooms that have a projector | 3 (Room 1.06, Room 2.01, Room 3.01) |
        ... Because no workspace has a seat count of 12, there is no room that meets the
        capacity requirement."

"no workspace has a seat count OF 12" was literally true and the conclusion was false. The
`seatCount` values are 6, 20, 22, 24, 26, 28, 30, 48 -- **none is exactly twelve** -- while
EIGHTEEN of twenty-eight seat twelve or more, three of them the very rooms the same answer had
just named as having projectors (30, 25 and 25 seats). An exact seat count is a coincidence, so
an equality reading returns nothing for almost any party size.

The rows were already in the prompt: the lane logged `whole-register fetch: WorkspaceProfile
(28 instances, 23 fields)`. So the arithmetic was left to the narration, which is the thing
`register_facts` exists to stop (BUG-581).
"""

import pytest

from orchestrator.services.register_facts import _AT_LEAST_RE, _at_least_lines

#: THE UNIT MARKER IS NOT AUTOMATIC, and without it this file is DESELECTED by `pytest -m
#: unit` -- the suite that gates a commit. Three test files written on 2026-10-01 were
#: missing it, so 61 tests ran green when invoked by name and protected nothing in the
#: gate. The tell was the summary line: `deselected` rose by exactly the number of tests
#: added while `passed` did not move.
pytestmark = pytest.mark.unit


def _size(question: str):
    m = _AT_LEAST_RE.search(question)
    if not m:
        return None
    return next((g for g in m.groups() if g), None)


def _rows(values, col="seatCount"):
    return [
        {"recordId": "WS-%02d" % i, col: str(v), "recordStatus": "active"}
        for i, v in enumerate(values)
    ]


#: The live `seatCount` values, read from the graph. None is exactly 12.
LIVE_SEATS = [6, 6, 8, 20, 20, 22, 24, 24, 26, 26, 28, 28, 30, 30, 30, 30, 48]


class TestTheSizeIsFound:
    @pytest.mark.parametrize(
        "question,expected",
        [
            ("Find a room for 12 with a projector, free 2-4pm today, near the cafe.", "12"),
            ("We need a room for a 12-person project workshop.", "12"),
            ("Team of 25 moving to level 5 next month - flag any environmental gotchas.", "25"),
            ("Show me rooms that fit 20 theatre-style with blackout blinds.", "20"),
            ("Find the best room for an all-hands: fits 60, cool, low echo, near toilets.", "60"),
            ("What's the wet weather plan - which indoor overflow spaces hold 150?", "150"),
            ("We expect about 40 people at a research seminar.", "40"),
        ],
    )
    def test_a_party_size_is_read(self, question, expected):
        assert _size(question) == expected


class TestWhatIsNotAPartySize:
    """Every one of these is a real question from the bank or the gate (BUG-1399's measurement).

    Two were FALSE POSITIVES found by reading all 17 bank matches rather than trusting the count:
    "200 person-hours" is a unit and "hold 22 degrees" is a temperature.
    """

    @pytest.mark.parametrize(
        "question",
        [
            # a unit that merely contains "person"
            "Notify cleaning when meeting room occupancy passes 200 person-hours since last clean.",
            # a TEMPERATURE, and "hold" is one of the triggers
            "Confirm the exam hall will hold 22 degrees and low noise for three hours from 9.",
            # a duration -- `register_projection._DURATION_RE` owns this shape
            "Show me the register for 2 hours of work",
            "What was the energy use for 3 days?",
            # a clock time
            "Which rooms are free at 2pm?",
            "free 2-4pm today",
            # a YEAR, which is why the digit cap is three and not four
            "Show me the readings for 2026",
            "Compare energy for 2026 and 2025",
        ],
    )
    def test_not_read_as_a_party_size(self, question):
        assert _size(question) is None, (
            "%r was read as a party size; a minimum-capacity line would then be stated about "
            "something that is not a number of people" % question
        )


class TestTheCountIsAFloor:
    def test_the_live_values_meet_twelve_although_none_equals_it(self):
        """The exact arithmetic of the defect, over the values the graph holds."""
        assert 12 not in LIVE_SEATS, "the premise of this test is that no value equals 12"
        lines = _at_least_lines(
            _rows(LIVE_SEATS), ["recordId", "seatCount", "recordStatus"], "a room for 12"
        )
        assert lines, "no minimum line was stated for a question naming a size"
        text = " ".join(lines)
        expected = sum(1 for v in LIVE_SEATS if v >= 12)
        assert f"{expected} of {len(LIVE_SEATS)}" in text, text
        assert "MINIMUM" in text
        assert "NEVER say none meets it" in text

    def test_a_genuine_shortfall_is_stated_as_one(self):
        """The opposite case must not be papered over: say it falls short of the largest."""
        lines = _at_least_lines(
            _rows([4, 6, 8]), ["recordId", "seatCount", "recordStatus"], "a room for 50"
        )
        text = " ".join(lines)
        assert "none reaches 50" in text, text
        assert "largest" in text

    def test_roomcapacity_is_read_as_well_as_seatcount(self):
        """Two registers spell it differently; the column's own words decide, not a literal."""
        lines = _at_least_lines(
            _rows([8, 12, 20, 25, 30, 50], col="roomCapacity"),
            ["recordId", "roomCapacity", "recordStatus"],
            "a room for 12",
        )
        assert lines and "5 of 6" in " ".join(lines), lines


class TestSilenceWhenEitherHalfIsMissing:
    """A count against a floor nobody asked for is noise; an invented column is worse."""

    def test_no_size_in_the_question_states_nothing(self):
        assert (
            _at_least_lines(
                _rows(LIVE_SEATS), ["recordId", "seatCount", "recordStatus"], "Who owns these?"
            )
            == []
        )

    def test_no_numeric_people_column_states_nothing(self):
        rows = [{"recordId": "D-1", "recordOwner": "Estates", "recordStatus": "active"}]
        assert (
            _at_least_lines(rows, ["recordId", "recordOwner", "recordStatus"], "a room for 12")
            == []
        )

    def test_a_non_numeric_capacity_value_states_nothing(self):
        """`capacity` on the building is the string "about 500 people" — not a filterable number."""
        rows = [{"recordId": "B-1", "capacity": "about 500 people", "recordStatus": "active"}]
        assert (
            _at_least_lines(rows, ["recordId", "capacity", "recordStatus"], "a room for 12") == []
        )
