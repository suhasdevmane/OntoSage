# -*- coding: utf-8 -*-
"""Filter first, truncate second (BUG-337 (b), measured live 2026-08-27).

"Where can I fill my water bottle?" answered *"I don't have that specific
information on record"* about a building with TWELVE bottle-refill points.

The chain, from the live log:

1. Every one of the building's drinking-water amenities scores exactly 2 for that
   query -- "water" is a lay term on all of them, so they TIE.
2. ``resolve()`` cut the tied list to the presentation size of three, keeping an
   arbitrary three: all labelled "Drinking water point", none labelled "Bottle
   refill point".
3. The caller's on-topic guard then CORRECTLY rejected all three, because none of
   them mentions a bottle.
4. Nothing survived, so the building denied having a thing it has twelve of.

No single step was wrong. Truncating before the caller filters is the defect, and
the tie was only what exposed it. The resolver now returns candidates and the
caller truncates after filtering and ranking.

The residual, also measured live: "on floor 3" listed floors 0, 1 and 2 and never
mentioned 3, because nothing in the ranking looked at the floor an amenity
declares. Ranked, not filtered -- the other floors' points are still true.
"""

import inspect

import pytest

from orchestrator.agents.capability_agent import (
    _PRESENT_FACTS,
    _floor_in_question,
    _same_floor,
)
from orchestrator.services.capability_graph_resolver import _MAX_FACTS, _MIN_SCORE

pytestmark = pytest.mark.unit


# -- the coupling that caused it ---------------------------------------------
def test_the_resolver_returns_more_candidates_than_the_answer_shows():
    """If these are equal, the caller's on-topic filter has nothing to choose from
    and the arbitrary tie-break decides the answer."""
    assert _MAX_FACTS > _PRESENT_FACTS


def test_the_resolver_does_not_truncate_to_the_presentation_size():
    from orchestrator.services import capability_graph_resolver as cgr

    src = inspect.getsource(cgr.CapabilityGraphResolver.resolve)
    assert "scored[:_MAX_FACTS]" in src
    assert "scored[:3]" not in src


def test_the_caller_truncates_after_filtering_and_ranking():
    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent)
    order_filter = src.index("filter_on_topic")
    order_sort = src.index("_pairs.sort(key=_relevance")
    order_cut = src.index("[:_PRESENT_FACTS]")
    assert order_filter < order_sort < order_cut, "truncation must come last"


def test_the_minimum_score_still_admits_a_single_distinctive_term():
    """Raising the cut must not have moved the bar for what counts as a match."""
    assert _MIN_SCORE == 2


# -- the floor residual ------------------------------------------------------
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Where can I fill my water bottle on floor 3?", "3"),
        ("nearest toilet on level 2", "2"),
        ("storey 0 please", "0"),
        ("Where can I fill my bottle?", ""),
        ("what is the temperature", ""),
    ],
)
def test_the_floor_a_question_names(question, expected):
    assert _floor_in_question(question) == expected


@pytest.mark.parametrize(
    "declared,asked,expected",
    [
        ("Floor3", "3", True),
        ("3", "3", True),
        ("Level 3", "3", True),
        ("Floor0", "3", False),
        ("", "3", False),
        # a declaration with no digits must not match everything
        ("Rooftop", "3", False),
        ("Basement", "0", False),
    ],
)
def test_floor_matching_compares_digits_not_spelling(declared, asked, expected):
    """Buildings spell it Floor3, 3, or Level 3. Comparing strings would make the
    ranking depend on a building's house style."""
    assert _same_floor(declared, asked) is expected


def test_the_floor_outranks_the_other_signals():
    """A floor named in the question is the strongest signal there is: it is what
    the questioner explicitly asked for."""
    from orchestrator.agents import capability_agent

    src = inspect.getsource(capability_agent)
    idx = src.index("def _relevance(pair):")
    window = src[idx : idx + 500]
    assert "_asked_floor and _same_floor" in window
    # first element of the returned tuple == highest sort priority
    ret = window[window.index("return (") : window.index("return (") + 200]
    assert ret.index("_same_floor") < ret.index("_is_on_topic")


def test_the_amenity_carries_the_floor_the_building_declares():
    """The ranking cannot use a field the resolver never read."""
    from orchestrator.services import capability_graph_resolver as cgr

    src = inspect.getsource(cgr)
    assert "ontosage:onFloor ?floor" in src
    assert 'on_floor=_v("floor")' in src
    assert "on_floor=am.on_floor" in src
    assert "on_floor: str" in src
