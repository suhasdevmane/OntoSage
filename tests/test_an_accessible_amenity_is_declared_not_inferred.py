# -*- coding: utf-8 -*-
""""No toilet is reachable" was wrong twice over (V10 W0-7).

WHAT WENT WRONG
---------------
    "Nearest accessible toilet to room 3.10?"
      -> "No toilet is reachable from 3.10 in the floor-plan adjacency data."

The floor-plan adjacency genuinely could not answer it. The BUILDING could: a toilet on
that very floor, and two verified accessible WCs on Floor 4 and Floor 0. For someone with
mobility needs *"no toilet is reachable"* and *"the accessible one is one floor up"* are not
degrees of the same answer -- the first ends a journey.

AND THEN THE FIX WAS WRONG IN A WORSE WAY
-----------------------------------------
The first version of the fallback decided accessibility by searching for words like
"accessible" and "wheelchair" across each amenity's lay terms. Every ordinary toilet in this
building carries `"toilet, toilets, washroom, restroom, bathroom, wc, accessible toilet"` --
lay terms exist so that somebody TYPING those words finds a toilet. So the fallback reported
11 of 12 amenities as accessible and told a wheelchair user that the toilet on their own
floor was accessible, when the accessibility register records verified accessible WCs only
on floors 0 and 4.

That is a worse answer than the decline it replaced, and it is the exact shape the
accessible-route mapping warns about in its own header: an accessible route asserted from
anything but a survey is a guess about a person's journey.

SO: ACCESSIBILITY IS A DECLARED, VERIFIED FACT.
`ontosage:accessibilityVerified true` on an `ontosage:AccessibilityFeature`. Lay terms find
a thing; they never establish what it is. Unverified is not accessible.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from orchestrator.services.amenity_proximity import (  # noqa: E402
    AmenityHit,
    floor_number,
    nearest_by_floor,
    render,
    wants_accessible,
)

_NS = "http://ontosage.org/capabilities#"


def _exec(rows):
    """A fake SPARQL executor. Each row: (iri, label, floor, located, lays, classes, verified)."""

    async def run(_q):
        return {
            "results": {
                "bindings": [
                    {
                        "a": {"value": r[0]},
                        "label": {"value": r[1]},
                        "floor": {"value": r[2]},
                        "located": {"value": r[3]},
                        "lays": {"value": r[4]},
                        "classes": {"value": r[5]},
                        "acc_verified": {"value": r[6]},
                    }
                    for r in rows
                ]
            }
        }

    return run


#: The building as it actually is: ordinary toilets whose LAY TERMS say "accessible
#: toilet", and two separately declared, verified accessible WCs.
_REAL_SHAPE = [
    (
        "x#Amenity_ToiletFacility_Floor3",
        "Toilet facility - Room 3.02",
        "Floor3",
        "x#Room3.02",
        "toilet, toilets, washroom, restroom, bathroom, wc, accessible toilet",
        f"{_NS}ToiletFacility",
        "",
    ),
    (
        "x#Amenity_ToiletFacility_Floor1",
        "Toilet facility - Room 1.07",
        "Floor1",
        "x#Room1.07",
        "toilet, wc, accessible toilet",
        f"{_NS}ToiletFacility",
        "",
    ),
    (
        "x#access_accessible_wc_4",
        "Accessible WC - Floor 4",
        "",
        "x#Floor4",
        "accessible toilet, disabled toilet, wheelchair toilet",
        f"{_NS}AccessibilityFeature",
        "true",
    ),
    (
        "x#access_accessible_wc_0",
        "Accessible WC - Floor 0",
        "",
        "x#Floor0",
        "accessible toilet, disabled toilet",
        f"{_NS}AccessibilityFeature",
        "true",
    ),
]


# ── the trap ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_lay_term_does_not_make_an_amenity_accessible():
    """The load-bearing test. This is the failure that would strand somebody."""
    hits = await nearest_by_floor(
        _exec(_REAL_SHAPE), _NS, ["toilet", "wc"], from_floor=3, accessible_only=True
    )
    locals_ = [h.local for h in hits]
    assert "Amenity_ToiletFacility_Floor3" not in locals_, (
        "an ordinary toilet was reported as accessible because its LAY TERMS -- which "
        "exist so people searching those words find a toilet -- contain 'accessible "
        "toilet'. This tells a wheelchair user the toilet on their floor is usable."
    )
    assert set(locals_) == {"access_accessible_wc_4", "access_accessible_wc_0"}


@pytest.mark.asyncio
async def test_an_unverified_accessibility_feature_is_not_accessible():
    """Unverified is not accessible -- the accessibility register's own doctrine."""
    rows = list(_REAL_SHAPE)
    rows.append(
        (
            "x#access_accessible_wc_2",
            "Accessible WC - Floor 2 (awaiting survey)",
            "",
            "x#Floor2",
            "accessible toilet",
            f"{_NS}AccessibilityFeature",
            "",  # declared, never verified
        )
    )
    hits = await nearest_by_floor(
        _exec(rows), _NS, ["toilet", "wc"], from_floor=3, accessible_only=True
    )
    assert "access_accessible_wc_2" not in [h.local for h in hits], (
        "an unsurveyed feature was offered as accessible; a feature nobody has checked is "
        "a different answer from one that has been"
    )


# ── the answer it exists to give ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_nearest_accessible_wc_is_ordered_by_floor_distance():
    hits = await nearest_by_floor(
        _exec(_REAL_SHAPE), _NS, ["toilet", "wc"], from_floor=3, accessible_only=True
    )
    assert hits[0].local == "access_accessible_wc_4", "Floor 4 is one away from Floor 3"


@pytest.mark.asyncio
async def test_the_answer_states_that_the_asker_s_own_floor_has_none():
    """The fact somebody plans around."""
    hits = await nearest_by_floor(
        _exec(_REAL_SHAPE), _NS, ["toilet", "wc"], from_floor=3, accessible_only=True
    )
    out = render(hits, "toilet", "Room 3.10", 3, True)
    assert "no accessible toilet recorded on Room 3.10's floor" in out
    assert "1 floor up" in out


@pytest.mark.asyncio
async def test_an_ordinary_request_still_finds_the_toilet_on_this_floor():
    """Not accessibility-filtered: the Floor 3 toilet is the right answer."""
    hits = await nearest_by_floor(
        _exec(_REAL_SHAPE), _NS, ["toilet", "wc"], from_floor=3, accessible_only=False
    )
    out = render(hits, "toilet", "Room 3.10", 3, False)
    assert "same floor" in out


def test_the_answer_never_claims_to_be_a_route():
    """Floors apart is not walking distance, and a lift may be out of service."""
    hits = [AmenityHit(iri="x#a", label="Accessible WC - Floor 4", floor="Floor4", accessible=True)]
    out = render(hits, "toilet", "Room 3.10", 3, True)
    assert "not a surveyed route" in out
    assert "lift is in service" in out


# ── floor parsing, without assuming a grammar ────────────────────────────────


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Floor3", 3),
        ("Level 3", 3),
        ("L3", 3),
        ("3", 3),
        ("Floor-1", -1),
        # A building naming floors in words yields no number, and the caller then says the
        # floor is not recorded rather than guessing one.
        ("Ground", None),
        ("Mezzanine", None),
        ("", None),
    ],
)
def test_a_floor_number_is_read_not_assumed(text, expected):
    assert floor_number(text) == expected


@pytest.mark.asyncio
async def test_an_amenity_with_no_floor_sorts_last_not_nearest():
    """Treating "unknown" as "here" is how a confident wrong answer is built."""
    rows = [
        ("x#far", "Accessible WC - Floor 5", "Floor5", "", "accessible", f"{_NS}AccessibilityFeature", "true"),
        ("x#nowhere", "Accessible WC - location unrecorded", "", "", "accessible", f"{_NS}AccessibilityFeature", "true"),
    ]
    hits = await nearest_by_floor(
        _exec(rows), _NS, ["wc"], from_floor=3, accessible_only=True
    )
    assert [h.local for h in hits] == ["far", "nowhere"]


# ── the question's own words ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Nearest accessible toilet to room 3.10?", True),
        ("step-free route to the toilet", True),
        ("wheelchair accessible WC", True),
        ("Nearest toilet to room 3.10?", False),
        ("where is the kitchen", False),
    ],
)
def test_the_question_says_whether_accessibility_was_asked_for(question, expected):
    assert wants_accessible(question) is expected


# ── wired ────────────────────────────────────────────────────────────────────


def test_the_spatial_lane_tries_the_catalogue_before_declining():
    import inspect

    from orchestrator.agents import spatial_agent

    src = inspect.getsource(spatial_agent)
    assert "_nearest_from_amenities" in src
    assert "fallback = await self._nearest_from_amenities(" in src, (
        "the amenity fallback is defined and never called, so the floor-plan decline "
        "still stands as the final answer"
    )


def test_the_fallback_runs_after_the_adjacency_search_not_instead_of_it():
    """A surveyed route beats a floor count whenever one exists."""
    import inspect

    from orchestrator.agents.spatial_agent import SpatialAgent

    src = inspect.getsource(SpatialAgent._answer_nearest)
    assert src.index("rf.nearest(") < src.index("_nearest_from_amenities"), (
        "the catalogue is consulted before the floor plan, so a real adjacency route "
        "would be replaced by a floor count"
    )

# ── the floor the asker is on (found by the live probe, 2026-09-07) ──────────


def test_the_reference_floor_comes_from_the_manifest_not_the_zone_id():
    """`3.10` is on floor THREE, and its trailing number is TEN.

    `Space` carries no floor field, so the helper's fallback -- the trailing number of the
    zone id -- was the only thing that ever ran. The live probe answered:

        "There is no accessible toilet recorded on 3.10's floor. The nearest is
         Accessible WC - Floor 4 (Fourth Floor) - 6 floors down."

    Floor 4 is ONE FLOOR UP from floor 3. Every offline test passed, because they all
    supply `from_floor` directly and none exercised the derivation. This pins the source
    instead: the manifest knows which floor it draws, and guessing a floor from an
    identifier is the grammar assumption the lexicon work exists to stop making.
    """
    import inspect

    from orchestrator.agents.spatial_agent import SpatialAgent

    caller = inspect.getsource(SpatialAgent._answer_nearest)
    assert "int(_m.floor)" in caller, (
        "the reference floor is no longer read from the manifest that contains the space"
    )

    helper = inspect.getsource(SpatialAgent._nearest_from_amenities)
    assert "floor_number(getattr(" not in helper, (
        "the helper derives the floor from the zone id again; `3.10` reads as floor 10"
    )
    assert "from_floor" in inspect.signature(SpatialAgent._nearest_from_amenities).parameters


@pytest.mark.asyncio
async def test_a_missing_reference_floor_says_so_rather_than_computing_a_distance():
    """None must not become zero. A distance from a floor nobody established is a
    confident number with nothing behind it."""
    hits = await nearest_by_floor(
        _exec(_REAL_SHAPE), _NS, ["toilet", "wc"], from_floor=None, accessible_only=True
    )
    out = render(hits, "toilet", "Some Room", None, True)
    assert "floor is not recorded" in out
    assert "floor up" not in out and "floor down" not in out
