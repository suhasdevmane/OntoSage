# -*- coding: utf-8 -*-
"""A register too large to hand over whole is narrowed, not dropped (BUG-430).

`_whole_register` returned None whenever a register exceeded `MAX_RECORD_ROWS`, on the
stated reasoning that a building "with thousands of bookings will fall back, which is
correct". Falling back IS correct. What happened after it was not.

Measured live once the timetable was lifted into 675 sessions:

    Q: "Which teaching sessions are scheduled in Room 1.06 this month?"
    A: "the data you provided only lists spaces and the number of sensors in each area"

Routing had already established the question was about `TimetabledSession`. That knowledge
was then discarded, the generated fallback asked about sensor counts, and a register holding
the answer produced an answer about something else. The same question now returns the 23
sessions in that room.

**Nothing is truncated.** A question that names nothing specific — "which rooms have the
most timetabled sessions?" — still declines, because handing over an arbitrary 120 of 675
would answer a superlative from a fifth of the data and look authoritative doing it. That is
the failure mode this codebase has paid for repeatedly, and it is worse than no answer.
"""

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def agent_cls():
    from orchestrator.agents.sparql_agent import SPARQLAgent

    return SPARQLAgent


def test_an_identifier_in_the_question_becomes_the_scope(agent_cls):
    assert agent_cls._scope_tokens("Which sessions are in Room 1.06 this month?") == ["1.06"]
    assert agent_cls._scope_tokens("Show me permit PTW-0042") == ["ptw-0042"]
    assert agent_cls._scope_tokens("What is happening on 2026-09-10?") == ["2026-09-10"]


def test_a_question_naming_nothing_specific_yields_no_scope(agent_cls):
    """The load-bearing case: no scope means decline, not an arbitrary slice."""
    assert agent_cls._scope_tokens("Which rooms have the most timetabled sessions?") == []
    assert agent_cls._scope_tokens("how many are there?") == []


def test_ordinary_words_are_not_treated_as_scope(agent_cls):
    """A filter built from common words matches most of a register and scopes nothing."""
    tokens = agent_cls._scope_tokens("Which sessions are scheduled next month?")
    for stop in ("which", "scheduled", "next", "month"):
        assert stop not in tokens


def test_a_literal_is_escaped_before_it_reaches_sparql(agent_cls):
    """The tokens come from user text and are interpolated into a FILTER."""
    assert agent_cls._escape_literal('a"b') == 'a\\"b'
    assert agent_cls._escape_literal("a\\b") == "a\\\\b"


def test_the_scope_is_capped(agent_cls):
    """A question full of identifiers must not build an unbounded filter."""
    q = " ".join(f"Room {n}.0{n}" for n in range(1, 9))
    assert len(agent_cls._scope_tokens(q)) <= 6


def test_the_size_limit_still_exists(agent_cls):
    """Scoping is not a licence to hand over any register whole."""
    assert isinstance(agent_cls.MAX_RECORD_ROWS, int)
    assert 0 < agent_cls.MAX_RECORD_ROWS <= 1000


def test_the_oversized_path_still_declines_without_tokens():
    """Pinned by reading the source: no tokens must return None before any query runs."""
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._whole_register)
    # Anchor on the CODE, not the first textual match: the explanatory comment above the
    # branch names MAX_RECORD_ROWS too, and an earlier version of this test read that
    # instead and failed on prose.
    idx = src.find("if record.instances > self.MAX_RECORD_ROWS:")
    assert idx > 0, "the oversized-register branch has moved or gone"
    window = src[idx : idx + 500]
    assert "_scope_tokens" in window, "the oversized branch no longer builds a scope"
    assert "return None" in window, (
        "the oversized branch must still decline when the question names nothing specific"
    )
