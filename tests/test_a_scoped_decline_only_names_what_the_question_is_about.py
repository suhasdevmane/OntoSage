# -*- coding: utf-8 -*-
"""Wave 8 (tail J): the 'does measure' clause, the quantity that is not a place, foot traffic, topics.

Four defects from one unseen set, pinned together because they share a cause: a sentence said
something true about the building that was not what the reader asked about, or something false.

1. "This building does measure occupancy (512 series); ask for it" under "Are there any
   accessibility features available near me?" — the binder bound occupancy from the word
   "available". The clause is only for a quantity the QUESTION's own words name.
2. "'efficiency' does not exist in this building" — a quantity word gated and worded as an absent
   room. A quantity is "not something this building measures".
3. "No — of foot traffic is not measured" — garbled by the idiom "keep track OF", and false: the
   events store records entrance arrival counts.
4. "I did not find any accessibility-related features" — the building records accessible toilets,
   lifts, step-free routes and a hearing loop; the capability resolver, which the failing lane never
   asked, matches them.

Every graph read is a fake.
"""

from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.services import absence_second_chance as sc
from orchestrator.services import observability as ob
from orchestrator.services import referent_resolver as rr

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_concept_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    """The concept resolver would try GraphDB; a unit test must not reach for the network."""
    from orchestrator.services.concept_resolver import concept_resolver

    async def none(text: str) -> List[Any]:
        return []

    monkeypatch.setattr(concept_resolver, "resolve", none)


OCCUPANCY = NS(
    quantity_label="occupancy", classes=("Motion_Sensor", "Occupancy_Count_Sensor"), sensors=[]
)


def concept(brick: List[str]) -> List[Dict[str, Any]]:
    return [{"brick_classes": brick}]


# ── 1. the clause is for a quantity the question names ──────────────────────────────────────────


@pytest.mark.parametrize(
    "question, brick, about",
    [
        (
            "Are there free parking spaces available now?",
            ["ontosage:Parking_Occupancy_Sensor"],
            True,
        ),
        ("are there any devices left on in unoccupied rooms?", ["brick:Motion_Sensor"], True),
        ("Is there anyone in the lobby?", ["brick:Occupancy_Count_Sensor"], False),
        ("Are there any accessibility features available near me?", ["brick:Motion_Sensor"], False),
        (
            "Which project option remains preferred when cost, carbon assumptions are varied?",
            ["brick:Electric_Energy_Sensor"],
            False,
        ),
        (
            "Before my hybrid seminar, which installed AV, network and power services are ready?",
            ["brick:Electric_Power_Sensor"],
            False,
        ),
    ],
)
def test_a_bound_quantity_is_reported_only_when_the_question_names_it(
    question: str, brick: List[str], about: bool
) -> None:
    binding = OCCUPANCY
    if "energy" in brick[0].lower() or "power" in brick[0].lower():
        binding = NS(
            quantity_label="energy submeter", classes=(brick[0].split(":")[1],), sensors=[]
        )
    assert sc.binding_is_about_question(question, concept(brick), binding) is about


def test_a_decision_question_never_names_a_quantity_however_many_words_it_shares() -> None:
    binding = NS(quantity_label="energy submeter", classes=("Electric_Energy_Sensor",), sensors=[])
    assert not sc.binding_is_about_question(
        "Which option has the lowest energy cost?",
        concept(["brick:Electric_Energy_Sensor"]),
        binding,
    ), "not a direct ask for a state or a figure"


@pytest.mark.asyncio
async def test_an_unrelated_bound_quantity_is_not_a_candidate_at_all() -> None:
    class Unrelated(sc.Reach):
        async def measurable(self, question: str, results: Dict[str, Any]) -> Any:
            return None  # what GraphReach.measurable returns for an unrelated binding

    shape = sc.detect_absence_shape("The register does not record any accessibility features.")
    assert shape is not None
    assert (
        await sc.probe(
            "Are there any accessibility features available near me?",
            shape,
            {},
            Unrelated(),
            "metadata",
        )
        == []
    )


# ── 2. a quantity is not a place ────────────────────────────────────────────────────────────────


def test_a_refused_quantity_is_not_worded_as_an_absent_room() -> None:
    quantity = rr.ReferentResolution(
        status=rr.NOT_FOUND, referent="efficiency", kind=rr.KIND_MEASURAND
    )
    place = rr.ReferentResolution(status=rr.NOT_FOUND, referent="swimming pool", kind=rr.KIND_SPACE)
    assert rr.absence_reason(quantity) == (
        "'efficiency' is not something this building measures, so there is nothing to report about it"
    )
    assert "does not exist in this building" not in rr.absence_reason(quantity)
    assert rr.absence_reason(place) == (
        "'swimming pool' does not exist in this building, so there is nothing to report about it"
    )


def test_an_old_style_resolution_with_no_kind_keeps_the_original_wording() -> None:
    legacy = rr.ReferentResolution(status=rr.NOT_FOUND, referent="Room 9.99")
    assert rr.absence_reason(legacy).endswith(
        "does not exist in this building, so there is nothing to report about it"
    )


def test_the_gate_records_the_kind_it_refused() -> None:
    import inspect

    assert "kind=typed.kind" in inspect.getsource(rr.ReferentResolver._resolve_typed)


# ── 3. foot traffic ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "question, named",
    [
        ("How do you keep track of foot traffic in the lobby?", "foot traffic"),
        ("Can you measure radiation in the atrium?", "radiation"),
        ("Can you monitor the noise here?", "noise"),
        ("Do you track of occupancy?", "occupancy"),
    ],
)
def test_the_idiom_keep_track_of_does_not_leak_of_into_the_quantity(
    question: str, named: str
) -> None:
    assert ob.named_quantity(question) == named


@pytest.mark.asyncio
async def test_foot_traffic_is_recorded_in_the_events_store() -> None:
    assert await ob.recorded_elsewhere("foot traffic") == "entrance arrival counts"
    assert await ob.recorded_elsewhere("of foot traffic") == "entrance arrival counts"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "quantity", ["radiation", "radon", "voltage fluctuation", "efficiency", ""]
)
async def test_a_quantity_no_store_records_is_still_not_measured(quantity: str) -> None:
    """True absences survive: nothing recorded elsewhere means the negative stands."""
    assert await ob.recorded_elsewhere(quantity) == ""


# ── 4. what the building's own amenity triples say ──────────────────────────────────────────────


class FakeFact:
    def __init__(self, label: str, answer: str = "", note: str = "", location: str = ""):
        self.label, self.answer, self.note, self.location = label, answer, note, location

    def render(self) -> str:
        return f"**{self.label}**. {self.answer or self.note}"


class TopicReach(sc.Reach):
    def __init__(self, facts: List[FakeFact]):
        self._facts = facts
        self.asked = 0

    async def topics(self, question: str) -> List[Any]:
        self.asked += 1
        return self._facts


ACCESS_Q = "Are there any accessibility features available near me?"
ACCESS_A = (
    "I'm sorry, but the building's records do not contain any information about "
    "accessibility-related features."
)


@pytest.mark.asyncio
async def test_the_building_records_its_own_accessibility_features_and_a_second_look_finds_them() -> (
    None
):
    reach = TopicReach(
        [FakeFact("Accessibility", answer="Step-free routes, accessible toilets, a hearing loop.")]
    )
    shape = sc.detect_absence_shape(ACCESS_A)
    assert shape is not None
    found = await sc.probe(ACCESS_Q, shape, {}, reach, "metadata")
    assert found and found[0].kind == "topic" and found[0].tier == "A"
    assert "hearing loop" in sc.topic_answer(found[0])


@pytest.mark.asyncio
async def test_the_capability_lane_is_not_asked_twice() -> None:
    reach = TopicReach([FakeFact("Accessibility", answer="x")])
    shape = sc.detect_absence_shape(ACCESS_A)
    assert shape is not None
    assert await sc.probe(ACCESS_Q, shape, {}, reach, "capability") == []
    assert reach.asked == 0


@pytest.mark.asyncio
async def test_a_topic_replaces_the_decline_through_the_one_lane_call() -> None:
    reach = TopicReach(
        [FakeFact("Accessibility", answer="Step-free routes and accessible toilets.")]
    )

    async def topic(candidate: sc.Candidate, question: str) -> Optional[str]:
        return sc.topic_answer(candidate)

    state = NS(intermediate_results={}, user_message="")
    rep = await sc.absence_second_chance(
        ACCESS_Q, ACCESS_A, "metadata", state, reach=reach, answerers=sc.Answerers(topic=topic)
    )
    assert rep is not None and rep.reopened and "Step-free routes" in rep.text
    assert "do not contain any information" not in rep.text


@pytest.mark.asyncio
async def test_no_matching_topic_leaves_the_decline_standing() -> None:
    state = NS(intermediate_results={}, user_message="")
    rep = await sc.absence_second_chance(
        "Is there a swimming pool?",
        "The register does not record any swimming pool.",
        "metadata",
        state,
        reach=TopicReach([]),
        answerers=sc.Answerers(topic=lambda c, q: None),
    )
    assert rep is None


def test_a_topic_the_question_does_not_name_is_never_a_candidate() -> None:
    """Measured: a long question about suppression systems was matched to the catering topic."""
    catering = FakeFact("Catering Amenities", answer="A cafe and vending machines.")
    assert (
        sc.topic_candidate(
            [catering],
            "Has any gaseous, foam, kitchen or other specialist suppression system entered alarm?",
        )
        is None
    ), "not a direct ask, and no word of the label is in the question"
    assert (
        sc.topic_candidate([catering], "Are there any vending machines or a cafe?") is None
    ), "the label's words ('catering', 'amenities') are not in the question"
    named = sc.topic_candidate([catering], "Are there any catering amenities near me?")
    assert named is not None and named.kind == "topic"


def test_a_long_question_never_reaches_a_topic_even_when_a_label_word_appears_in_it() -> None:
    quiet = FakeFact("Quiet Study", answer="Open-plan study areas on floors 1 and 2.")
    long_question = (
        "Is the calibration chain traceable and accurate enough for the smallest difference "
        "or threshold the study intends to interpret?"
    )
    assert sc.topic_candidate([quiet], long_question) is None
