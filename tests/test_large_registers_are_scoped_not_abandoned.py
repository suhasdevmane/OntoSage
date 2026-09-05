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
    """No tokens must return None rather than hand over an arbitrary slice.

    Asserted on the SOURCE's structure, not on one line of it: an earlier version of this
    test anchored on the literal `if record.instances > self.MAX_RECORD_ROWS:` and broke
    the moment that was refactored into a named `oversized` flag — a test failing on
    formatting rather than on behaviour.
    """
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._whole_register)
    assert "MAX_RECORD_ROWS" in src, "the row limit is gone"
    assert "_scope_tokens" in src, "the handover no longer builds a scope"
    assert "oversized" in src and "not tokens" in src, (
        "the oversized branch must still decline when the question names nothing specific; "
        "handing over an arbitrary slice answers a superlative from part of the data"
    )


def test_a_wide_register_is_bounded_by_cells_not_rows_alone():
    """82 rows is inside the row limit and still too large to hand over (BUG-433).

    The stakeholder register is 82 rows — well under MAX_RECORD_ROWS — and 1,558 pivoted
    cells, and the model returned an EMPTY COMPLETION for it: the user got nothing at all.
    A row limit cannot separate it from the registers that work, because it has FEWER
    columns than two of them.
    """
    from orchestrator.agents.sparql_agent import SPARQLAgent

    assert isinstance(SPARQLAgent.MAX_RECORD_CELLS, int)
    # Measured on bldg1: the largest register that works is 816 cells, the one that fails
    # is 1,558. The budget must sit between them or it either declines working registers
    # or lets the failing one through.
    assert 816 < SPARQLAgent.MAX_RECORD_CELLS < 1558, (
        f"MAX_RECORD_CELLS={SPARQLAgent.MAX_RECORD_CELLS} does not sit between the largest "
        f"register that works (816) and the one that does not (1,558)"
    )


def test_a_cell_oversized_register_is_re_fetched_scoped_not_declined():
    """The cell check must not be a dead end.

    Its first version measured the whole fetch and returned None, so a register that was
    merely WIDE was never scoped at all: "which stakeholder groups does DEP-13 serve?"
    names a code that narrows it to three records, and the answer was still "no such
    records appear in the triples supplied".
    """
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._whole_register)
    assert "re-fetching scoped" in src, (
        "a cell-oversized register is declined without ever being scoped"
    )
    assert src.index("MAX_RECORD_CELLS") < src.rindex("return None"), (
        "the cell check must run before the final decline, or the retry is unreachable"
    )


def test_the_size_is_measured_after_the_pivot():
    """Estimate and measurement must be in the same unit.

    Counting RAW BINDINGS instead of pivoted cells measured a 24-row register at 792
    against a 624 estimate, declined four working answers, and took the regression probe
    from 23/25 to 19/25. Provenance predicates are the difference; every lifted record
    carries them and no mapping mentions them.
    """
    import inspect

    from orchestrator.agents.sparql_agent import SPARQLAgent

    src = inspect.getsource(SPARQLAgent._whole_register)
    pivot_at = src.index("_pivot_by_subject(bindings)")
    cells_at = src.index("MAX_RECORD_CELLS")
    assert pivot_at < cells_at, (
        "the cell budget is applied before the pivot, so it is counting triples against a "
        "budget written in records times columns"
    )
