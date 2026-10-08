"""v2: a space's KIND, in the building's own words, as a facet every space carries.

Measured live, 2026-10-08: "Which floor has the most meeting rooms?" was answered "Floor 5 ... 2"
for a building whose labels put four meeting rooms on Floor 3, because the only kind-like facets
were two registers that mention 42 and 28 of 234 spaces. Offline, synthetic building.
"""

from dataclasses import dataclass, field
from typing import Tuple

import pytest

from orchestrator.services.deliberation import facet_resolvers as fr
from orchestrator.services.deliberation.cqir import (
    FacetCriterion,
    FacetOperator,
    Hardness,
)
from orchestrator.services.deliberation.facets import Facet, FacetCatalogue
from orchestrator.services.deliberation.space_kinds import (
    SPACE_KIND_FACET,
    kind_matches,
    space_kinds,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "label, classes, expected",
    [
        (
            "Room 7.17 — Huddle Room",
            ("Conference_Room", "Room"),
            ("Huddle Room", "Conference Room"),
        ),
        ("Room 2.01 — Wet Laboratory", ("Laboratory", "Room"), ("Wet Laboratory", "Laboratory")),
        ("Quiet Pod — Level 2", ("Room",), ("Quiet Pod",)),  # an unnumbered label: kind first
        ("Room 9.99", ("Office", "Room"), ("Office",)),  # no descriptor: the Brick class
        ("Room 9.98", ("Room",), ()),  # nothing but the generic class: untyped
    ],
)
def test_a_space_is_its_label_descriptor_then_its_brick_classes(label, classes, expected):
    assert space_kinds(label, classes) == expected


def test_a_requested_kind_matches_when_all_its_words_are_one_kinds_words():
    seminar = space_kinds("Room 1.25 — Conference/Seminar Room", ("Conference_Room",))
    huddle = space_kinds("Room 7.17 — Huddle Room", ("Conference_Room",))
    lab = space_kinds("Room 2.01 — Wet Laboratory", ("Laboratory",))
    assert kind_matches("seminar rooms", seminar) and not kind_matches("seminar rooms", huddle)
    assert kind_matches("huddle room", huddle) and not kind_matches("huddle room", seminar)
    # both carry Conference_Room, so asking for that class reaches both
    assert kind_matches("conference room", seminar) and kind_matches("conference room", huddle)
    assert kind_matches("labs", lab) and kind_matches("laboratories", lab)
    assert kind_matches("rooms", lab)  # a generic word names every space


@dataclass
class _Cand:
    space_iri: str
    label: str
    kinds: Tuple[str, ...] = field(default_factory=tuple)


def _criterion(value, op=FacetOperator.EQUALS):
    return FacetCriterion(facet=SPACE_KIND_FACET, operator=op, value=value, hardness=Hardness.HARD)


def test_the_resolver_reads_the_candidates_and_never_queries():
    facet = Facet(
        key=SPACE_KIND_FACET,
        entity_type="space",
        source_kind="spatial",
        label="kind of space",
        value_type="enum",
        status="suitable",
        coverage=3,
    )
    cands = [
        _Cand("http://x/b#r1", "Room 1.01 — Huddle Room", ("Conference_Room", "Room")),
        _Cand("http://x/b#r2", "Room 1.02 — Office", ("Office", "Room")),
        _Cand("http://x/b#r3", "Room 1.03", ("Room",)),
    ]

    async def no_sparql(query):  # pragma: no cover - must not be called
        raise AssertionError("the kind of a space is read from the candidate")

    import asyncio

    checks = asyncio.run(
        fr.resolve_facets(
            [_criterion("huddle rooms")],
            FacetCatalogue([facet]),
            [c.space_iri for c in cands],
            no_sparql,
            candidates=cands,
        )
    )
    status = {c.space_iri.rsplit("#", 1)[-1]: c.status for c in checks}
    assert status == {"r1": fr.MET, "r2": fr.UNMET, "r3": fr.UNKNOWN}
