# -*- coding: utf-8 -*-
"""BUG-949 — a scope constraint the compiler could not bind is DECLARED, not omitted.

Three of the fourteen weird answers in the held-out tail M share one cause (hand-read
2026-09-29):

    #5  "Which eligible PUBLIC SEATING AREA has lower glare and a more stable temperature?"
        -> ranked Research Laboratories and Academic Offices
    #30 "Which MEETING ROOM has the best natural light and lowest CO2 right now?"
        -> ranked Academic Offices

Both answers carefully declared what they DID score — "'lower glare' scored as minimize
illuminance against the 0-500 band" — and said nothing whatever about the constraint they could
not apply. A reader has no way to tell that "seating area" was ignored rather than satisfied.

MEASURED AT THE COMPILER, inside the container with all 45 real modalities:

    "Which room ON FLOOR 3 is warmest?"          -> spatial=[('on_floor','floor3','on floor 3')]
    "...public seating area..."                  -> spatial=[]
    "...meeting room..."                         -> spatial=[]

`SpatialQualifier.anchor` is documented as "floor label, amenity kind, or space name" and a room
TYPE is none of those, so nothing is recorded — and `build_assumptions`, which iterates
`cqir.constraints` (all modality constraints), had no signal to disclose from.

THE WORDING COPIES AN EXISTING PRECEDENT in the same function, added for the same reason: row 99
of the 2026-09-17 read asked about "next Wednesday after 2 p.m." and was told the ranking was
"forecast 24h ahead from recent history" — a sentence that reads as though next Wednesday had
been projected. *The number is the same; the claim it makes must not be.*

WHAT MAKES IT SAFE, and the reason half these tests are negatives: a qualifier that IS a scored
modality is not a dropped filter. "Is there a LOW-NOISE area on this floor" names noise, which
the lane really does score, so reporting it as unapplied would be a false caveat — worse than
no caveat at all.
"""

from __future__ import annotations

import inspect

import pytest

from orchestrator.services.deliberation.clarify_policy import (
    _NOT_A_TYPE,
    _SPACE_HEADS,
    build_assumptions,
    unbound_space_type,
)

pytestmark = pytest.mark.unit


class _C:
    """The few CQIR fields this reads, so the test needs no live compiler."""

    def __init__(self, query, spatial=(), constraints=()):
        self.raw_query = query
        self.spatial = list(spatial)
        self.constraints = list(constraints)
        self.time = _T()

    class _Noop:
        pass


class _T:
    basis = None
    source_phrase = ""
    horizon_hours = 0


class _Dir:
    """`build_assumptions` reads `direction.value`, so the stub carries a real enum shape."""

    value = "minimize"


class _Con:
    def __init__(self, modality, source_phrase=""):
        self.modality = modality
        self.source_phrase = source_phrase
        self.weight = 1.0
        self.direction = _Dir()
        self.threshold_source = None


# ── when a constraint really was dropped ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "Which eligible public seating area has lower glare and a more stable temperature?",
            "seating area",
        ),
        (
            "Which meeting room has the best natural light and lowest CO2 right now?",
            "meeting room",
        ),
        ("Is there a quiet office free this afternoon?", "quiet office"),
    ],
)
def test_a_space_type_the_compiler_could_not_bind_is_reported(query, expected):
    c = _C(query, spatial=(), constraints=(_Con("illuminance", "lower glare"),))
    assert unbound_space_type(c) == expected


def test_the_declaration_says_it_does_not_describe_only_that_kind():
    """The load-bearing half of the sentence. Without it the caveat reads as an apology rather
    than a limit on what the ranking means."""
    c = _C(
        "Which meeting room has the best natural light?",
        constraints=(_Con("illuminance", "natural light"),),
    )
    texts = [a.text for a in build_assumptions(c)]
    said = [t for t in texts if "could not narrow" in t]
    assert said, texts
    assert "does not describe only meeting rooms" in said[0]


# ── when it was NOT dropped: the negatives are the point ──────────────────────────────


def test_a_qualifier_that_is_a_scored_modality_is_not_a_dropped_filter():
    """ "low-noise area" names noise, and the lane scores noise. Reporting it as unapplied would
    be a FALSE caveat, which is worse than none — measured live, the lane really does rank on it."""
    c = _C(
        "Is there a low-noise area on this floor where I can work below 50 dB?",
        constraints=(_Con("noise", "low-noise"),),
    )
    assert unbound_space_type(c) is None


def test_nothing_is_reported_when_a_place_was_bound():
    c = _C("Which room on floor 3 is warmest?", spatial=[object()])
    assert unbound_space_type(c) is None


@pytest.mark.parametrize(
    "query",
    [
        "Which room is warmest right now?",  # a head noun with no type
        "Where is the best space to work?",  # "best" is not a kind of space
        "Which available room is quietest?",  # "available" is not a kind of space
        "What is the temperature in here?",  # no head noun at all
    ],
)
def test_no_type_named_means_no_declaration(query):
    assert unbound_space_type(_C(query)) is None


def test_the_determiner_list_excludes_superlatives_and_availability_words():
    """These are the words that would otherwise produce "I could not narrow to 'best space'",
    which says nothing and would appear on a large share of deliberative answers."""
    for word in ("which", "the", "any", "best", "nearest", "available", "eligible"):
        assert word in _NOT_A_TYPE, word


def test_the_head_nouns_are_generic_english():
    """A test in this package fails if any deliberation module names a building, a namespace or a
    zone id. These are ordinary nouns, so a building that calls its rooms something else simply
    gets no note — the safe direction."""
    for head in ("room", "area", "space", "office"):
        assert head in _SPACE_HEADS
    src = inspect.getsource(unbound_space_type)
    for literal in ("abacws", "bldg1", "cardiff"):
        assert literal not in src.lower()


def test_the_precedent_it_copies_is_named():
    """So a later maintainer finds the reasoning without hunting a tracker."""
    src = inspect.getsource(build_assumptions)
    assert "BUG-949" in src
    assert "the claim it makes must not be" in src
