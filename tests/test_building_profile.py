# -*- coding: utf-8 -*-
"""The building answering questions about ITSELF.

Measured against the survey corpus this was the largest class of unanswered
question, and none of it is about sensors — "how old is this building?", "who
built it?", "what type of building is this?", "are visitors allowed?". Of the
questions the corpus marked answerable, 30 of 44 got no data-backed answer, and
they were overwhelmingly this shape.

Two things had to be true for those to fail: no instance carried the facts, and
no code referenced the predicates that would hold them. These tests pin the
second half — that a building which DOES declare them gets answers, one which
does not is told so honestly, and neither outcome depends on which building is
active.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from orchestrator.services import building_profile as bp

pytestmark = pytest.mark.unit


# ── telling a question about the building from one about its contents ────────


@pytest.mark.parametrize(
    "query,facet",
    [
        ("How old is this building?", "age"),
        ("When was the building built?", "age"),
        ("What year was it built?", "age"),
        ("How big is this building?", "size"),
        ("What is the gross area?", "size"),
        ("What type of building is this?", "type"),
        ("Is this a commercial building?", "type"),
        ("Who owns this building?", "owner"),
        ("Who runs this building?", "operator"),
        ("Who built the building?", "architect"),
        ("Can you tell me who designed it?", "architect"),
        ("What is the address?", "address"),
        ("Are visitors allowed?", "access"),
        ("What is this building for?", "purpose"),
        ("How many storeys does it have?", "storeys"),
    ],
)
def test_a_question_about_the_building_itself_is_recognised(query, facet):
    assert bp.detect_facet(query) == facet


@pytest.mark.parametrize(
    "query",
    [
        # About the CONTENTS or live state — the metrics, sensor and spatial
        # paths answer these better, and must keep them.
        "How many sensors are there?",
        "How many rooms are on floor 2?",
        "What is the temperature in the building right now?",
        "What is the air quality in this building?",
        "Show me floor 1",
        "How many floors does this building have?",
        # Not about the building at all.
        "What is a VAV box?",
        "Who wrote Hamlet?",
    ],
)
def test_questions_about_contents_or_the_world_are_not_claimed(query):
    assert bp.detect_facet(query) is None


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_input_is_not_a_profile_question(blank):
    assert bp.detect_facet(blank) is None


def test_a_whole_profile_request_is_recognised():
    for q in ("Tell me about this building", "Describe the building", "building profile"):
        assert bp.detect_facet(q) == "__all__"


def test_the_name_question_is_answerable_without_any_declared_fact():
    """ "Do you have a name?" deflected in the corpus, though the building's own
    label already answers it."""
    assert bp.detect_facet("Do you have a name?") == "name"
    out = bp.render(bp.BuildingProfile(resolved=True), "name", "Some Building")
    assert "Some Building" in out


# ── the answer comes from the graph, whatever the graph happens to hold ──────


def _exec(pairs):
    """A fake SPARQL exec returning (predicate, value) rows."""

    async def _run(_q):
        return {"results": {"bindings": [{"p": {"value": p}, "v": {"value": v}} for p, v in pairs]}}

    return _run


B = bp.BRICK
O = bp.ONTOSAGE


async def test_a_declared_fact_is_answered_from_the_graph():
    prof = await bp.resolve("http://example.org/x#", _exec([(B + "yearBuilt", "1998")]))
    out = bp.render(prof, "age", "Test Building")
    assert "1998" in out and "Test Building" in out


async def test_the_age_answer_computes_years_rather_than_only_echoing_the_year():
    prof = await bp.resolve("http://example.org/x#", _exec([(B + "yearBuilt", "2000")]))
    out = bp.render(prof, "age", "T")
    assert "2000" in out and "years old" in out


async def test_a_building_that_declares_nothing_is_declined_not_invented():
    """The failure mode this prevents: an open-domain answerer supplying a
    plausible year that no one can falsify."""
    prof = await bp.resolve("http://example.org/x#", _exec([]))
    assert bp.render(prof, "age", "T") is None  # caller then declines
    hint = bp.enablement_hint("T")
    assert "yearBuilt" in hint and "no code changes" in hint.lower()


async def test_a_building_declaring_OTHER_facts_says_which_it_has():
    """Partial data must not read as a blanket "I know nothing" — the corpus
    shows people re-ask the same question differently when it does."""
    prof = await bp.resolve("http://example.org/x#", _exec([(O + "buildingOwner", "Acme")]))
    out = bp.render(prof, "age", "T")
    assert "doesn't state that" in out and "Owner" in out


async def test_the_whole_profile_lists_everything_declared():
    prof = await bp.resolve(
        "http://example.org/x#",
        _exec(
            [
                (B + "yearBuilt", "1998"),
                (O + "buildingOwner", "Acme"),
                (B + "buildingPrimaryFunction", "Office"),
            ]
        ),
    )
    out = bp.render(prof, "__all__", "T")
    assert "1998" in out and "Acme" in out and "Office" in out


async def test_an_area_is_given_a_unit_rather_than_a_bare_number():
    prof = await bp.resolve("http://example.org/x#", _exec([(B + "grossArea", "18400")]))
    out = bp.render(prof, "size", "T")
    assert "18,400" in out and "m²" in out


async def test_a_blank_node_placeholder_is_not_reported_as_a_value():
    """brick:area is sometimes a blank-node id in these ontologies; echoing it
    would be worse than saying nothing."""
    prof = await bp.resolve(
        "http://example.org/x#", _exec([(B + "grossArea", "n32c4720a45cf4235b3ca4ec5b38920fab1")])
    )
    assert not prof.has_any


async def test_a_graph_that_cannot_be_reached_says_so_rather_than_guessing():
    async def _boom(_q):
        raise RuntimeError("graphdb down")

    prof = await bp.resolve("http://example.org/x#", _boom)
    out = bp.render(prof, "age", "T")
    assert "couldn't look up" in out and "guess" in out


# ── building-agnosticism ─────────────────────────────────────────────────────


def test_the_resolver_names_no_building():
    import inspect

    src = inspect.getsource(bp).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys", "cardiff"):
        assert literal not in src, f"building profile must not name a building: {literal}"


def test_no_fact_value_is_hardcoded():
    """Every answer must come from the graph. A year, an owner or an area
    written into the code would be right for one building and wrong for the
    next."""
    import inspect
    import re

    src = inspect.getsource(bp)
    code = "\n".join(
        line.split("#")[0] for line in src.splitlines() if not line.strip().startswith("#")
    )
    # Namespace URIs legitimately carry digits that look like years
    # (w3.org/2000/01/rdf-schema); they are vocabulary identifiers, not facts.
    code = re.sub(r"https?://\S+", "", code)
    years = re.findall(r"\b(1[89]\d{2}|20[0-2]\d)\b", code)
    assert not years, f"a hardcoded year would be wrong for another building: {years}"
