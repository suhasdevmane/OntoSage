# -*- coding: utf-8 -*-
"""The building must never be named after whatever the query happened to return (BUG-421).

`sparql_agent` carried a special formatter:

    if "building" in uq and "name" in uq:
        b = bindings[0]
        return f"The building name is: **{label}**"

Two defects compounding. `"name" in uq` is a SUBSTRING test, so it matched the word
"names"; and the template then took the first binding's label **whatever the query was
about**. Measured live:

    Q: "Where do waste stream NAMES and labels conflict within a station?"
    A: "The building name is: **Reception mixed recycling**"

It named a waste bin as the building. A confident false statement about the building's own
identity is the worst shape of wrong answer this system can produce, and it is precisely
what contract 4 forbids — worse than declining, because nothing signals that it is wrong.

Three guards now: whole words rather than substrings, and a SINGLE binding, because a
building-name answer is one row by definition while a multi-row result is a different
question that happens to share two words.
"""

import inspect
import re

import pytest

pytestmark = pytest.mark.unit


def _guard_source() -> str:
    from orchestrator.agents import sparql_agent

    src = inspect.getsource(sparql_agent)
    idx = src.find("Special formatting for building name query")
    assert idx > 0, "the building-name formatter has moved or gone"
    return src[idx : idx + 1400]


def test_the_trigger_matches_whole_words_not_substrings():
    """'names' must not satisfy a test meant for 'name'."""
    guard = _guard_source()
    assert r"\bbuilding\b" in guard, "the building test is still a substring match"
    assert r"\b(name|named|called)\b" in guard, "the name test is still a substring match"


def test_the_template_requires_exactly_one_binding():
    """A building-name answer is one row. Anything else is a different question."""
    guard = _guard_source()
    assert "len(bindings) == 1" in guard, (
        "without this, a multi-row result still hands bindings[0] to the template and names "
        "the building after the first row of an unrelated query"
    )


@pytest.mark.parametrize(
    "question, should_fire",
    [
        ("what is the name of this building?", True),
        ("what is this building called?", True),
        ("which building is this, and what is it named?", True),
        # The measured failure, and its neighbours.
        ("where do waste stream names and labels conflict within a station?", False),
        ("which rooms have names that differ from the signage?", False),
        # "names" is plural, so the whole-word test alone already rejects it.
        ("list the names of every sensor in the building", False),
    ],
)
def test_the_word_test_behaves_as_intended(question, should_fire):
    """The word test in isolation, before the row-count guard."""
    fired = bool(
        re.search(r"\bbuilding\b", question) and re.search(r"\b(name|named|called)\b", question)
    )
    assert fired == should_fire, f"{question!r} -> {fired}, expected {should_fire}"


def test_a_multi_row_result_is_stopped_even_when_the_words_match():
    """Both guards together, which is the actual contract."""

    def would_answer(question: str, n_bindings: int) -> bool:
        words = bool(
            re.search(r"\bbuilding\b", question) and re.search(r"\b(name|named|called)\b", question)
        )
        return words and n_bindings == 1

    assert would_answer("what is the name of this building?", 1) is True
    assert would_answer("list the names of every sensor in the building", 24) is False
    assert would_answer("where do waste stream names conflict?", 24) is False
