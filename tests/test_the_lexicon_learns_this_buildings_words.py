# -*- coding: utf-8 -*-
"""Building-agnostic was asserted by a grep, so it was achieved as a grep (V10 W2-1).

WHAT THE LITERAL GUARD CANNOT SEE
---------------------------------
`scripts/check_building_literals.py` passes on this tree. The routing layer still carried
three regexes tuned against one building:

    _ROOM_ID_RE   = r"\\b(room|rm)[_\\s]?\\d+(\\.\\d+)?\\b"
    _ZONE_ID_RE   = r"\\bzone[_\\s][\\d]+\\.[\\d]+\\b"
    _SENSOR_ID_RE = r"\\b([A-Za-z][A-Za-z0-9]*_)+Sensor_[\\d.]+\\b"

None of them is a building LITERAL. A building numbering rooms `RM-204` matches none of
them -- the hyphen alone defeats the first -- and one naming rooms `Atrium` is invisible to
all three. The symptom is not an error: the question fails a bypass check, takes another
lane, and comes back plausibly wrong.

THE TEST THE REVIEW ASKED FOR
-----------------------------
The existing `test_contract_is_building_agnostic` greps six strings. It is replaced here by
a TWO-FIXTURE test: the lexicon is built over two entirely different room grammars, and
each must learn its own. A rule that only works for `N.NN` fails the second fixture.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
It does not delete the generic word lists. "temperature", "average", "last week" and "room"
are domain English, not one building's vocabulary. Replacing them with graph-derived terms
would make routing WORSE for every building -- one whose graph is still loading would lose
the ability to recognise a trend question at all. The lexicon AUGMENTS.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.building_lexicon import (  # noqa: E402
    BuildingLexicon,
    clear_cache,
    learn_shapes,
    lexicon_for,
    shape_of,
    strip_type_word,
)


# ── the identifier inside a name ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Room 5.01", "5.01"),
        ("Room_5.01", "5.01"),
        ("3.15 — Meeting Room", "3.15"),
        ("0.31 — Mechanical/Service Room", "0.31"),
        ("HVAC Zone 5.21", "5.21"),
        # The descriptive tail goes, ALL of it, including an identifier repeated
        # inside a bracket. Digging `5.34` out of `(Room 5.34)` would need a
        # heuristic about brackets, and this label costs nothing: the same room
        # appears elsewhere as `Room 5.34`, so the shape is learned anyway. What
        # is left here has no digit, so it is never shape-learned -- safe, not lost.
        ("Telecommunications Room — Floor 5 (Room 5.34)", "Telecommunications Room"),
        # Prefix KEPT: stripping `rm` would leave `204`, and a bare number matches far too
        # much free text to be a useful identifier.
        ("RM-204", "RM-204"),
        ("Server_Room_F5", "Server_Room_F5"),
        # No digit anywhere: a word-named space, returned whole.
        ("Atrium", "Atrium"),
        ("Long Gallery", "Long Gallery"),
    ],
)
def test_the_identifier_is_extracted_from_the_name(name, expected):
    assert strip_type_word(name) == expected


def test_the_descriptive_tail_is_not_part_of_the_identifier():
    """Feeding whole labels to the shape learner produced TWENTY shapes for one building.

    `3.15 — Meeting Room`, `3.17 — Staff Common Room`, `3.36 — Restroom (Male)` each
    generalise differently because the DESCRIPTION varies where the convention does not.
    Twenty shapes reads as "no convention", which is the wrong conclusion about a building
    that numbers every room N.NN.
    """
    labels = [
        "3.15 — Meeting Room",
        "3.17 — Staff Common Room",
        "3.36 — Restroom (Male)",
        "2.66 — Staff Break Room / Kitchen",
        "0.18 — Office",
    ]
    assert learn_shapes(labels) == (r"\d+\.\d+",), "the description leaked into the shape"


# ── two fixtures, two grammars ───────────────────────────────────────────────


@pytest.mark.parametrize(
    "names, expected_shape, matching, not_matching",
    [
        (
            ["Room 5.01", "Room 12.7", "Room 0.01"],
            r"\d+\.\d+",
            "what is the CO2 in room 5.01",
            "show me the trend for last week",
        ),
        (
            ["RM-204", "RM-118", "RM-9"],
            r"[A-Za-z]+\-\d+",
            "temperature in RM-204",
            "show me the trend for last week",
        ),
        (
            ["L2-East", "L3-West", "L1-North"],
            r"[A-Za-z]+\d+\-[A-Za-z]+",
            "occupancy in L2-East",
            "how many people are in the building",
        ),
    ],
)
def test_each_grammar_learns_its_own_shape(names, expected_shape, matching, not_matching):
    """The two-fixture test. A rule that only works for N.NN fails here."""
    lex = BuildingLexicon(identifier_shapes=learn_shapes(names))
    assert lex.identifier_shapes == (expected_shape,)
    assert lex.mentions_identifier(matching)
    assert not lex.mentions_identifier(not_matching)


def test_a_word_named_building_learns_no_shape_rather_than_a_bad_one():
    """`Atrium` and `Long Gallery` share no shape but "a word".

    Learning one would make every mention of any word look like a room reference. Saying
    nothing is correct; those spaces are matched exactly instead.
    """
    assert learn_shapes(["Atrium", "Long Gallery", "The Street"]) == ()


# ── the false positives that make a matcher useless ──────────────────────────


def test_a_type_word_and_a_bare_number_is_not_a_shape():
    """"Floor 4" generalises to `[A-Za-z]+ \\d+`, which matches ordinary English.

    Six floors would have made every sentence containing a word and a number look like a
    room reference: "over the last 7 days", "Windows 10", "COVID 19".
    """
    shapes = learn_shapes(["Floor 4", "Floor 3", "Level 2", "Room 5.01", "Room 1.02"])
    assert r"[A-Za-z]+\ \d+" not in shapes
    lex = BuildingLexicon(identifier_shapes=shapes)
    for innocent in ("over the last 7 days", "Windows 10 update", "compare floor 1 and floor 3"):
        assert not lex.mentions_identifier(innocent), f"false positive on {innocent!r}"


def test_too_many_shapes_means_no_convention_and_no_pattern():
    """A regex built from a dozen conventions matches almost any word.

    The first version of this fixture generated names from one formula, so all ten
    collapsed to ONE shape and the test passed for the wrong reason. Genuinely different
    conventions are needed to exercise the cap.
    """
    messy = ["A1", "B-2", "C_3", "4.5", "D6-E", "F_7.8", "G9_H"]
    assert learn_shapes(messy, max_shapes=3) == ()
    # And under a cap that admits them, the shapes come back.
    assert len(learn_shapes(messy, max_shapes=20)) > 3


# ── failure is empty, never wrong ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_an_unreachable_graph_yields_an_empty_lexicon():
    """Every caller then falls back to its generic list -- which is how routing behaved
    before this module existed, so an unreachable graph costs nothing that worked."""

    async def boom(_q):
        raise RuntimeError("graphdb down")

    clear_cache()
    lex = await lexicon_for("bX", "http://example.test/b#", boom)
    assert not lex.usable
    assert lex.identifier_pattern() is None
    assert not lex.mentions_identifier("what is the CO2 in room 5.01")


@pytest.mark.asyncio
async def test_the_lexicon_is_cached_per_building():
    calls = {"n": 0}

    async def counting(_q):
        calls["n"] += 1
        return {"results": {"bindings": []}}

    clear_cache()
    await lexicon_for("bY", "http://example.test/y#", counting)
    first = calls["n"]
    await lexicon_for("bY", "http://example.test/y#", counting)
    assert calls["n"] == first, "the lexicon was rebuilt; routing runs on every turn"

    clear_cache("bY")
    await lexicon_for("bY", "http://example.test/y#", counting)
    assert calls["n"] > first, "clear_cache did not force a rebuild"


# ── shape generalisation ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "identifier, expected",
    [
        ("5.01", r"\d+\.\d+"),
        ("12.7", r"\d+\.\d+"),
        ("RM-204", r"[A-Za-z]+\-\d+"),
        ("A1", r"[A-Za-z]+\d+"),
        ("Server_Room_F5", r"[A-Za-z]+_[A-Za-z]+_[A-Za-z]+\d+"),
    ],
)
def test_a_shape_generalises_the_characters_not_the_values(identifier, expected):
    """`5.01` and `12.7` must collapse, or a 234-room building yields 234 alternatives."""
    assert shape_of(identifier) == expected


def test_no_building_vocabulary_appears_in_the_module():
    import inspect

    from orchestrator.services import building_lexicon as mod

    src = inspect.getsource(mod).lower()
    for literal in ("abacws", "cardiff", "buildsys", "senghennydd", '"bldg1"'):
        assert literal not in src, f"{literal!r} appears in the lexicon module"
