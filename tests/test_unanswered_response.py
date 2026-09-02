# -*- coding: utf-8 -*-
"""When no lane produces a response, say something true rather than nothing (BUG-355).

"I processed your request, but couldn't generate a response" is the documented signature of
a lane that routes correctly, executes, and is never collected by `_response_node`. It has
been measured at least twice in this project — the observability lane (V6-T10) and the
diagnosis lane (BUG-354). The string is the worst available outcome: the user learns nothing
actionable, and whoever is debugging learns nothing about which component went quiet.

The replacement must state what was understood and which lane ran, and must state NO fact
about the building — there is nothing to state, and a plausible invention here is precisely
what the honesty contract forbids.
"""

import pytest

from orchestrator.workflow._orchestrator import _unanswered_response

pytestmark = pytest.mark.unit


class _State:
    def __init__(self, **results):
        self.intermediate_results = results


def test_the_opaque_placeholder_is_gone():
    text = _unanswered_response(_State(), None)
    assert "couldn't generate a response" not in text
    assert "could not generate a response" not in text


def test_it_names_the_intent_it_understood():
    text = _unanswered_response(_State(intent="sensor_data"), None)
    assert "sensor data" in text


def test_it_names_the_referents_it_extracted():
    text = _unanswered_response(_State(intent="sensor_data", entities=["Room 5.04"]), None)
    assert "Room 5.04" in text


def test_it_names_the_lane_that_ran_and_returned_nothing():
    """'Nothing was tried' and 'something was tried and came back empty' are different bugs."""
    text = _unanswered_response(_State(intent="sensor_data", sql_result={"rows": []}), None)
    assert "time-series lane" in text
    assert "returned nothing" in text


def test_it_says_so_when_no_lane_ran_at_all():
    text = _unanswered_response(_State(intent="general"), None)
    assert "No data lane produced a result" in text


def test_an_error_from_a_step_is_surfaced_not_swallowed():
    text = _unanswered_response(_State(error="sql: timeout after 30s"), None)
    assert "sql: timeout after 30s" in text


def test_it_does_not_claim_the_building_lacks_the_data():
    """The distinction matters: this is a gap in the system, not a fact about the building."""
    text = _unanswered_response(_State(intent="sensor_data", entities=["Room 5.04"]), None)
    assert "gap on my side" in text
    assert "not a statement that the building has no such data" in text


def test_it_offers_a_next_step():
    text = _unanswered_response(_State(), None)
    assert "Rephrasing" in text or "rephras" in text.lower()


def test_it_states_no_number():
    """Nothing supports a figure here, so no figure may appear."""
    import re

    text = _unanswered_response(_State(intent="sensor_data", entities=["Room 5.04"]), None)
    # The referent may contain digits; strip the echoed entities before checking.
    stripped = text.replace("Room 5.04", "")
    assert not re.search(r"\d+\.?\d*\s*(ppm|°C|C\b|%|lux|dB)", stripped)


def test_it_survives_a_state_with_no_results_at_all():
    class _Bare:
        pass

    assert _unanswered_response(_Bare(), None)
