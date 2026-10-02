# -*- coding: utf-8 -*-
"""Readings the lane bound and summarised are evidence the relevance gate may not delete.

MEASURED on the tail-O re-ask of 2026-10-02 (occupant01, /v1): "Is any area overheating right
now?" bound the 288 room-air temperature sensors, summarised them (max 25.9 degC) and was
replaced by "I couldn't put an answer together ..." because the gate judged the summary
OFF_TOPIC -- "does not give a direct yes/no answer". The same turn logged
`rows visibly read this turn=288`. An objection to the SHAPE of a grounded answer is a reason to
say so, not to substitute an untrue decline (BUG-873's rule, extended to the reading lane).

Narrow on purpose: only a yes/no THRESHOLD question about a measured quantity is protected
(12 of the 4,060 bank questions match the shape), and never one about CHANGE or a COMPARISON,
because "has humidity changed?" answered with current values IS off-topic and there the
deletion protects the reader (BUG-1252's pinned gap stays pinned for every other shape).
"""

from types import SimpleNamespace

import pytest

from orchestrator.workflow import _orchestrator as o

pytestmark = pytest.mark.unit


def _state(question, read):
    return SimpleNamespace(user_message=question, intermediate_results={"_read": read})


@pytest.fixture(autouse=True)
def _rows_read(monkeypatch):
    monkeypatch.setattr(o, "_store_rows_read", lambda state: state.intermediate_results["_read"])


class TestBoundReadingsAreEvidence:
    def test_a_present_state_question_with_bound_readings_is_protected(self):
        out = o._grounded_evidence_behind(_state("Is any area overheating right now?", 288))
        assert "288" in out and "readings" in out

    def test_no_readings_is_no_evidence(self):
        assert o._grounded_evidence_behind(_state("Is any area overheating right now?", 0)) == ""

    @pytest.mark.parametrize(
        "q",
        [
            "has humidity changed today?",
            "Is there a warmer area than the lobby?",
            "how do weekends compare to weekdays for energy use?",
            "What is the CO2 trend this week?",
            "Is it warmer than yesterday?",
        ],
    )
    def test_a_change_or_comparison_question_is_left_to_the_gate(self, q):
        assert o._grounded_evidence_behind(_state(q, 288)) == ""

    @pytest.mark.parametrize(
        "q", ["Is any area overheating right now?", "humidity safe", "Are the CO2 levels normal?"]
    )
    def test_a_threshold_question_is_the_protected_shape(self, q):
        assert o._THRESHOLD_YESNO_RE.search(q), q
        assert not o._CHANGE_OR_COMPARISON_RE.search(q), q
        assert o._grounded_evidence_behind(_state(q, 6)) != ""

    @pytest.mark.parametrize(
        "q",
        [
            "Do you adjust temperature based on how crowded it is?",  # control behaviour
            "what is the return air temperature right now?",  # the gate's own correct catch
            "Room available now?",
            "Which spaces are reserved this afternoon?",
        ],
    )
    def test_a_question_of_another_shape_is_left_to_the_gate(self, q):
        assert o._grounded_evidence_behind(_state(q, 275)) == ""
