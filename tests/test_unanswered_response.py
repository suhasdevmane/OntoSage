# -*- coding: utf-8 -*-
"""When no lane produces a response, say something a READER can use (BUG-355, BUG-706).

"I processed your request, but couldn't generate a response" is the documented signature of
a lane that routes correctly, executes, and is never collected by `_response_node`. It has
been measured at least twice in this project — the observability lane (V6-T10) and the
diagnosis lane (BUG-354).

Its first replacement fixed the wrong half. It said which LANE ran and called the outcome
"a gap on my side": diagnostics, addressed to a developer, printed at a facility manager.
The 2026-09-17 hand read of 147 live answers found it on six (rows 10, 35, 73, 83, 95, 119).

So the contract is now: the diagnosis goes to the log; the reader is told what was
understood, which part of the request the building has no vocabulary for, and what this
building does hold — derived live, never written down here. It still states no figure, and
still does not claim the building lacks the data.
"""

import re

import pytest

from orchestrator.services.grounding_guard import names_internal_vocabulary
from orchestrator.workflow import _orchestrator
from orchestrator.workflow._orchestrator import _unanswered_response

pytestmark = pytest.mark.unit


class _Record:
    """Stands in for `record_registry.RecordClass` — label, count and its own vocabulary."""

    def __init__(self, local_name, label, instances, terms=()):
        self.local_name = local_name
        self.label = label
        self.instances = instances
        self.terms = tuple(terms)


class _State:
    def __init__(self, user_message="", **results):
        self.intermediate_results = results
        self.user_message = user_message
        self.messages = []
        self.building_id = None


@pytest.fixture
def holdings(monkeypatch):
    """The building's live holdings, stubbed. Offline: nothing here touches the graph."""

    async def _fake(state, timeout_s=5.0):
        return (
            ["CO2", "humidity", "occupancy", "temperature"],
            [
                _Record("WorkOrder", "Work order", 412, ("work order", "work orders")),
                _Record("Booking", "Room booking", 88, ("room booking", "bookings")),
                _Record("CleaningTask", "Cleaning task", 30, ("cleaning task",)),
            ],
        )

    monkeypatch.setattr(_orchestrator, "_closest_holdings", _fake)
    return _fake


@pytest.fixture
def no_holdings(monkeypatch):
    """The graph could not be read. Nothing may be claimed about the building."""

    async def _fake(state, timeout_s=5.0):
        return ([], [])

    monkeypatch.setattr(_orchestrator, "_closest_holdings", _fake)
    return _fake


async def _text(state):
    return await _unanswered_response(state, None)


@pytest.mark.asyncio
async def test_the_opaque_placeholder_is_gone(holdings):
    text = await _text(_State())
    assert "couldn't generate a response" not in text
    assert "could not generate a response" not in text


@pytest.mark.asyncio
async def test_it_never_shows_the_intent_it_classified(holdings):
    """Defect C5: 'I read it as a question about **general** / **diagnosis** / **what to do**'.

    The classification is the pipeline's own vocabulary, wrong as often as right, and it told the
    reader nothing they could act on. It belongs in the log, which the next test pins.
    """
    for intent in ("sensor_data", "floor_plan", "general", "diagnosis", "recommend"):
        text = await _text(_State("anything", intent=intent))
        assert "I read it as" not in text
        assert "question about" not in text
        for shown in ("current readings", "what to do", "**general**", "**diagnosis**"):
            assert shown not in text, f"intent {intent!r} leaked into the reader's text: {shown!r}"


@pytest.mark.asyncio
async def test_it_names_the_referents_it_extracted(holdings):
    text = await _text(_State(intent="sensor_data", entities=["Room 5.04"]))
    assert "Room 5.04" in text


@pytest.mark.asyncio
async def test_it_never_names_an_internal_lane(holdings):
    """Rows 10, 35, 73, 83, 95, 119: 'the ontology lane, the time-series lane ran'.

    A lane is a component inside this program. To the person who asked the question it names
    nothing, so the sentence carries no information and reads as a fault report.
    """
    state = _State(
        "which rooms are stuffy",
        intent="sensor_data",
        sparql_result={"success": True},
        sql_result={"rows": []},
        analytics_result={"x": 1},
        capability_result={"y": 2},
    )
    text = await _text(state)
    assert names_internal_vocabulary(text) is None, (
        f"the fallback names machinery the reader cannot see: "
        f"{names_internal_vocabulary(text)!r}"
    )
    assert "gap on my side" not in text


@pytest.mark.asyncio
async def test_the_lane_diagnosis_still_reaches_the_log(holdings, caplog):
    """Moved, not deleted: 'nothing was tried' and 'it came back empty' are different bugs."""
    with caplog.at_level("WARNING"):
        await _text(_State("anything", intent="sensor_data", sql_result={"rows": []}))
    assert any("the time-series lane" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_it_says_what_the_building_does_hold(holdings):
    """Derived live — the point of the change is that the reader learns something."""
    text = await _text(_State("anything", intent="sensor_data"))
    assert "temperature" in text
    assert "Work order" in text


@pytest.mark.asyncio
async def test_it_claims_nothing_when_the_building_could_not_be_read(no_holdings):
    """An unreadable graph is not evidence about a building. No padding, no guess."""
    text = await _text(_State("anything", intent="sensor_data"))
    assert "does hold" not in text
    assert text.strip()


@pytest.mark.asyncio
async def test_an_abstract_question_is_answered_with_what_the_building_can_answer(holdings):
    """Row 119, verbatim. Superseded contract, and the reason is measured.

    This used to assert ONE question back, naming the word nothing matched. On the 2026-09-19
    development read that produced "Which measurement or record do you mean by **specialist** /
    **whole** / **weather**?" — a parser's guess quoted at a reader as though it were a field. An
    abstract, multi-part question is not missing a measurement, so it now gets no question back and
    the nearest things the building CAN answer instead. The referent shape below still asks.
    """
    text = await _text(
        _State(
            "Whats the best empty room to convert into two phone booths, by demand?",
            intent="recommend",
        )
    )
    assert "?" not in text, f"an abstract question is not answered with a question:\n{text}"
    assert "Which measurement or record do you mean by **" not in text
    assert "The nearest things I can answer are" in text
    assert "to anything this building records" not in text, "the pipeline's own phrasing"
    assert "authoris" not in text, "a stemmer artefact must never reach a reader"
    for glue in ("convert into", "booths by"):
        assert glue not in text, "a word was paired with glue instead of a content word"


@pytest.mark.asyncio
async def test_a_question_that_points_at_one_thing_still_asks_which_one(holdings):
    """The shape that IS a missing referent keeps its single question back."""
    text = await _text(_State("What happened during the incident?", intent="diagnosis"))
    assert text.count("?") == 1
    assert text.startswith("Which incident do you mean?")


@pytest.mark.asyncio
async def test_a_fully_mapped_question_is_not_asked_back_at(holdings):
    """Every word maps, so there is no 'part' to name; a bare re-ask would be noise."""
    text = await _text(_State("show me the work orders", intent="metadata"))
    assert "Which measurement or record" not in text
    assert text.count("?") == 0


@pytest.mark.asyncio
async def test_an_internal_error_is_for_an_administrator_only(holdings):
    """A non-admin cannot act on a step failure; an admin is the person who can."""
    reader = _State("anything", error="sql: timeout after 30s", user_role="facility_manager")
    assert "timeout after 30s" not in await _text(reader)
    admin = _State("anything", error="sql: timeout after 30s", user_role="admin")
    assert "timeout after 30s" in await _text(admin)


@pytest.mark.asyncio
async def test_it_does_not_claim_the_building_lacks_the_data(holdings):
    """Not answering and not holding are different facts; this text must not merge them."""
    text = await _text(_State("anything", intent="sensor_data", entities=["Room 5.04"]))
    assert "has no such data" not in text
    assert "no data" not in text.lower()


@pytest.mark.asyncio
async def test_it_states_no_number(holdings):
    """Nothing supports a reading here, so no reading may appear."""
    text = await _text(_State("anything", intent="sensor_data", entities=["Room 5.04"]))
    stripped = text.replace("Room 5.04", "")
    assert not re.search(r"\d+\.?\d*\s*(ppm|°C|C\b|%|lux|dB)", stripped)


@pytest.mark.asyncio
async def test_it_survives_a_state_with_no_results_at_all(no_holdings):
    class _Bare:
        pass

    assert await _unanswered_response(_Bare(), None)


def test_the_reader_is_not_shown_an_internal_intent_name():
    """'I read it as a **recommend** question' is our vocabulary, not the reader's."""
    from orchestrator.workflow._orchestrator import _intent_in_plain_words

    assert _intent_in_plain_words("recommend") == "what to do"
    assert _intent_in_plain_words("metadata") == "what the building records"
    # An intent nobody mapped still reads as words, never as snake_case.
    assert "_" not in _intent_in_plain_words("some_new_intent")
