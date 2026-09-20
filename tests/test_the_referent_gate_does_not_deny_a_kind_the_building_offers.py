# -*- coding: utf-8 -*-
"""The referent gate refuses what the building lacks, and steps aside for what it offers.

Measured on the 2026-09-20 read (tail G): "car parking is eligible for that building" was answered
"'car parking' does not exist in this building, so there is nothing to report about it" while the
graph holds an `ontosage:ParkingArea` (Ground Level Parking, six EV chargers) and another lane
answers "where can I park" correctly. The compound failed only on its modifier — "car" is in no
field beside "parking" — the head was found, and the refusal was built anyway.

Two steps-aside are pinned, and four true absences that must NOT step aside:

* a head the building holds with nothing same-kind to suggest is not an absence of the kind;
* a head that an ontosage AMENITY class names is a kind the building offers, so the compound is a
  way of asking for it, not a different place;
* "swimming pool", "escalator" and an unknown room id are still refused, and "west wing" keeps its
  ordinary clarification, because "which wing?" is a real question.

The graph is a fake: a list of (class local name) the amenity query answers for.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit

NS = "http://example.org/bldg#"


class FakeGraph:
    """Answers the resolver's queries from a set of words each entity kind is known by."""

    def __init__(self, entity_words: List[str], amenity_classes: List[str], suggest: List[str]):
        self.entity_words = entity_words
        self.amenity_classes = amenity_classes
        self.suggest = suggest
        self.queries: List[str] = []

    async def __call__(self, query: str) -> Dict[str, Any]:
        self.queries.append(query)
        hit: Any = []
        if "ontosage.org/capabilities#" in query and "REGEX(?w" in query:
            # the amenity-kind query: a whole-word match on the class's CamelCase words
            word = query.split('"(^|[^a-z0-9])')[1].split("s?")[0]
            hit = [{"s": {"value": "x"}}] if word in self.amenity_classes else []
        elif "SELECT ?s WHERE" in query and "?local" in query:
            # the existence query: every term must sit in ONE field
            wanted = [t for t in query.split('CONTAINS(?local, "')[1:]]
            words = [w.split('"')[0] for w in wanted]
            hit = (
                [{"s": {"value": "x"}}]
                if words
                and all(any(w in e for e in self.entity_words) for w in words)
                and len({w for w in words}) == 1
                else []
            )
        elif "?name" in query or "SELECT DISTINCT ?label" in query or "rdfs:label ?l" in query:
            hit = [
                {"label": {"value": s}, "l": {"value": s}, "s": {"value": s}} for s in self.suggest
            ]
        return {"results": {"bindings": hit}}


def typed(phrase: str, head: str, kind: str = rr.KIND_SPACE) -> rr.TypedReferent:
    return rr.TypedReferent(kind=kind, token="|".join(phrase.split()), phrase=phrase, head=head)


async def resolve(
    graph: Any, referent: rr.TypedReferent, suggestions: List[str]
) -> rr.ReferentResolution:
    resolver = rr.ReferentResolver(graph)

    async def exists(terms: List[str], namespace: str) -> bool:
        return len(terms) == 1 and any(terms[0] in w for w in graph.entity_words)

    async def suggest(terms: List[str], namespace: str, kind: str = "") -> List[str]:
        return suggestions

    resolver._exists_terms = exists  # type: ignore[assignment]
    resolver._exists_whole_words = exists  # type: ignore[assignment]
    resolver._suggest_terms = suggest  # type: ignore[assignment]
    return await resolver._resolve_typed(referent, NS, "the building")


@pytest.mark.asyncio
async def test_a_compound_whose_head_an_amenity_class_names_is_not_refused() -> None:
    graph = FakeGraph(["parking_level_ground"], amenity_classes=["parking"], suggest=[])
    res = await resolve(graph, typed("car parking", "parking"), ["Ground Level Parking"])
    assert res.status == rr.SKIPPED, "the gate steps aside and lets the lanes answer"


@pytest.mark.asyncio
async def test_a_head_the_building_holds_with_nothing_to_suggest_is_not_an_absence() -> None:
    graph = FakeGraph(["parking_level_ground"], amenity_classes=[], suggest=[])
    res = await resolve(graph, typed("car parking", "parking"), [])
    assert res.status == rr.SKIPPED


@pytest.mark.asyncio
async def test_a_referent_whose_head_is_unknown_is_still_refused() -> None:
    """swimming pool, escalator: the building lacks the KIND, and the gate says so."""
    graph = FakeGraph(["parking_level_ground"], amenity_classes=["parking"], suggest=[])
    res = await resolve(graph, typed("swimming pool", "pool"), [])
    assert res.status == rr.NOT_FOUND
    assert res.referent == "swimming pool"


@pytest.mark.asyncio
async def test_a_head_that_is_a_kind_of_place_keeps_its_clarification() -> None:
    """ "west wing": no amenity class says "wing", so 'which wing?' is still the right reply."""
    graph = FakeGraph(["east_wing"], amenity_classes=["parking"], suggest=["East Wing"])
    res = await resolve(graph, typed("west wing", "wing"), ["East Wing"])
    assert res.status == rr.NOT_FOUND
    assert "East Wing" in res.message


@pytest.mark.asyncio
async def test_an_amenity_class_is_matched_as_a_whole_word() -> None:
    """A carpool is not a pool: only a whole CamelCase word of an ontosage class counts."""
    graph = FakeGraph(["carpool_bay"], amenity_classes=["carpool"], suggest=["Carpool Bay"])
    res = await resolve(graph, typed("swimming pool", "pool"), ["Carpool Bay"])
    assert res.status == rr.NOT_FOUND


@pytest.mark.asyncio
async def test_a_failed_amenity_check_refuses_rather_than_guesses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = FakeGraph(
        ["parking_level_ground"], amenity_classes=[], suggest=["Ground Level Parking"]
    )
    resolver = rr.ReferentResolver(graph)

    async def exists(terms: List[str], namespace: str) -> bool:
        return len(terms) == 1

    async def suggest(terms: List[str], namespace: str, kind: str = "") -> List[str]:
        return ["Ground Level Parking"]

    async def boom(head: str) -> bool:
        raise RuntimeError("graph down")

    resolver._exists_terms = lambda t, n: (_false() if len(t) > 1 else exists(t, n))  # type: ignore
    resolver._suggest_terms = suggest  # type: ignore[assignment]
    resolver._holds_amenity_kind = boom  # type: ignore[assignment]
    res = await resolver._resolve_typed(typed("car parking", "parking"), NS, "the building")
    assert res.status == rr.NOT_FOUND, "an unreadable graph never turns a refusal into an answer"


async def _false() -> bool:
    return False
