"""The floor-scoped template must PARSE, or the floor silently stops applying (BUG-631).

`_floor_scoped_sparql` appended `PREFIX ref:` with a comment saying it was absent from the
standard prefix block. It had since been added to that block, so every floor-scoped query
GraphDB received was rejected outright:

    MALFORMED QUERY: Multiple prefix declarations for prefix 'ref'

Nothing announced it. The agent fell back, and the fallback takes the first 40 instances of
the class with NO spatial constraint — so "What is the air quality on floor 3?" was answered
from sensors labelled 5.02 and 5.03: the right class, the wrong floor, stated with confidence
and a plausible number.

A query that does not parse is not a slow query or a wrong answer; it is no query at all, and
the only thing standing between that and a fabricated answer is the fallback's willingness to
substitute. So the query is PARSED here rather than eyeballed.
"""

import pytest

from orchestrator.agents.sparql_agent import SPARQLAgent

pytestmark = pytest.mark.unit


def _agent():
    return SPARQLAgent.__new__(SPARQLAgent)


def _parse(query: str):
    """Parse with rdflib's SPARQL parser — the same grammar a triple store applies."""
    from rdflib.plugins.sparql import prepareQuery

    return prepareQuery(query)


_FLOOR_QUESTIONS = [
    ("What is the air quality on floor 3?", "brick:Air_Quality_Sensor"),
    ("average CO2 on floor 1", None),
    ("compare temperature between floor 1 and floor 5", None),
    ("what is the humidity on level 2", None),
    ("which floor is the warmest right now", None),
    ("noise on floor 4", None),
]


@pytest.mark.parametrize("question,class_target", _FLOOR_QUESTIONS)
def test_every_floor_scoped_query_parses(question, class_target):
    query = _agent()._floor_scoped_sparql(question, class_target)
    if query is None:
        pytest.skip("this question does not use the floor-scoped template")
    _parse(query)  # raises on malformed SPARQL


@pytest.mark.parametrize("question,class_target", _FLOOR_QUESTIONS)
def test_no_prefix_is_declared_twice(question, class_target):
    """The specific fault: two PREFIX lines for one prefix rejects the whole query."""
    query = _agent()._floor_scoped_sparql(question, class_target)
    if query is None:
        pytest.skip("this question does not use the floor-scoped template")
    declared = [
        line.split()[1].rstrip(":")
        for line in query.splitlines()
        if line.strip().startswith("PREFIX ")
    ]
    duplicates = {p for p in declared if declared.count(p) > 1}
    assert not duplicates, f"declared twice: {sorted(duplicates)}"


def test_the_prefix_block_is_asked_not_remembered():
    """The comment said `ref:` was not in the standard block; it was. Whatever the block
    declares today, the template must not re-declare it."""
    agent = _agent()
    block = agent._prefix_block()
    query = agent._floor_scoped_sparql("What is the air quality on floor 3?", "brick:Air_Quality_Sensor")
    for line in block.splitlines():
        if line.strip().startswith("PREFIX "):
            prefix = line.split()[1]
            assert query.count(f"PREFIX {prefix}") == 1, f"{prefix} declared more than once"


def test_the_floor_filter_survives_into_the_query():
    """A parsing query that dropped its floor filter would fail this suite's whole point."""
    query = _agent()._floor_scoped_sparql("average CO2 on floor 1", None)
    assert query is not None
    assert "?floorNum" in query and 'IN ("1")' in query


def test_the_offline_parser_would_NOT_have_caught_this():
    """Worth knowing, and worth writing down: rdflib ACCEPTS a duplicated prefix, and
    GraphDB rejects it. So the parse test above is necessary and was never sufficient — the
    duplicate-prefix test is the one with teeth here, and a green parse is not proof that a
    store will accept the query."""
    _parse(  # does not raise, though a real store returns MALFORMED QUERY
        "PREFIX ref: <https://a#>\nPREFIX ref: <https://b#>\n"
        "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
    )


def test_the_duplicate_detector_fails_on_a_planted_duplicate():
    """The guard has to fail on a bad query or it guards nothing."""
    planted = (
        "PREFIX ref: <https://a#>\nPREFIX ref: <https://b#>\n"
        "SELECT ?s WHERE { ?s ?p ?o } LIMIT 1"
    )
    declared = [
        line.split()[1].rstrip(":")
        for line in planted.splitlines()
        if line.strip().startswith("PREFIX ")
    ]
    assert {p for p in declared if declared.count(p) > 1} == {"ref"}


def test_a_genuinely_malformed_query_is_caught_by_the_parser():
    with pytest.raises(Exception):
        _parse("SELECT ?s WHERE { ?s ?p ")
