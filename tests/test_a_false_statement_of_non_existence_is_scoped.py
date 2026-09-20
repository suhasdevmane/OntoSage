# -*- coding: utf-8 -*-
"""'This building does not have X' is rewritten when the building holds X, and left alone when not.

The worst class in the 2026-09-20 read (tail G) was not a decline but a FALSE ASSERTION, which a
reader believes: "This building does not have occupancy sensors" (467 occupancy series exist),
"'car parking' does not exist in this building" (a ParkingArea exists), "the building does not
track embodied carbon" (said from one irrelevant approval record).

`absence_second_chance` needs an absence-led answer, and none of these has the shape of one. The
false-existence check needs nothing of the answer's shape: ANY sentence that says the building lacks
<X> is resolved, and rewritten to the scoped form only when <X> is something the building HOLDS.

What is pinned:

* the sentence forms that are recognised, and the ones that are results and never claims;
* a held sensor, amenity or register turns the claim into a scoped statement that says the
  building does hold it;
* every TRUE absence survives — a swimming pool, an escalator, radiation, an unknown room;
* privacy, control and observability results are never rewritten, and a rewrite never replaces the
  rest of the answer.

Every read of the graph is a fake, so nothing here needs a service.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from orchestrator.services import absence_second_chance as sc

pytestmark = pytest.mark.unit


class HoldingReach(sc.Reach):
    """A reach that holds exactly the things it is told to hold."""

    def __init__(self, held: Optional[Dict[str, sc.Held]] = None):
        self._held = held or {}
        self.asked: List[str] = []

    async def holds(self, subject: str) -> Optional[sc.Held]:
        self.asked.append(subject)
        return self._held.get(subject)


OCCUPANCY = sc.Held("sensor", "occupancy", 467)
PARKING = sc.Held("amenity", "Ground Level Parking")
WORK_ORDERS = sc.Held("register", "Work order", 24)


# ── 1. what counts as a claim ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "sentence, subject",
    [
        ("This building does not have occupancy sensors.", "occupancy sensors"),
        ("The building doesn't track embodied carbon.", "embodied carbon"),
        ("This building has no EV chargers.", "EV chargers"),
        (
            "'car parking' does not exist in this building, so there is nothing to report about it.",
            "car parking",
        ),
    ],
)
def test_the_sentence_forms_that_deny_a_kind_are_recognised(sentence: str, subject: str) -> None:
    claims = sc.find_lack_claims(sentence)
    assert claims and claims[0].subject == subject


@pytest.mark.parametrize(
    "sentence",
    [
        "There are no rooms above 25 degrees right now.",  # a RESULT SET
        "This building does not have any free desks today.",  # a state, not a kind
        "'Room 9.99' does not exist in this building.",  # an identifier, not a kind
        "Floor 3 averaged 780 ppm of CO2 yesterday.",
        "",
    ],
)
def test_a_result_a_state_or_an_id_is_never_read_as_a_claim_about_a_kind(sentence: str) -> None:
    assert sc.find_lack_claims(sentence) == []


def test_device_words_alone_name_nothing() -> None:
    assert sc.find_lack_claims("This building does not have any sensors.") == []
    assert sc.lack_terms("occupancy sensors") == ["occupanc"] or sc.lack_terms(
        "occupancy sensors"
    ) == ["occupancy"]


# ── 2. what is rewritten ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_denied_sensor_the_building_holds_is_rewritten_to_say_it_measures_it() -> None:
    answer = (
        "The building's records do not contain any information about who is in the lobby. "
        "**This building does not have occupancy sensors.** The only sensor data is evacuation."
    )
    out, changes = await sc.rewrite_false_existence(
        answer, HoldingReach({"occupancy sensors": OCCUPANCY})
    )
    assert "does not have occupancy sensors" not in out
    assert "I did not find occupancy sensors in the records I searched." in out
    assert "**does** measure occupancy (467 series)" in out
    assert "who is in the lobby" in out, "the rest of the answer is the lane's and is kept"
    assert changes == [
        {
            "claimed_missing": "occupancy sensors",
            "held": "occupancy",
            "kind": "sensor",
            "how": "does_not_have",
        }
    ]


@pytest.mark.asyncio
async def test_a_denied_amenity_the_building_offers_is_rewritten() -> None:
    answer = (
        "'car parking' does not exist in this building, so there is nothing to report about it."
    )
    out, changes = await sc.rewrite_false_existence(answer, HoldingReach({"car parking": PARKING}))
    assert "does not exist" not in out
    assert "This building does keep Ground Level Parking." in out
    assert changes[0]["kind"] == "amenity"


@pytest.mark.asyncio
async def test_a_denied_register_is_rewritten_to_name_it() -> None:
    out, _ = await sc.rewrite_false_existence(
        "The building has no work orders.", HoldingReach({"work orders": WORK_ORDERS})
    )
    assert "does keep Work order records, which I can read for you." in out


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "answer",
    [
        "'swimming pool' does not exist in this building, so there is nothing to report about it.",
        "'escalator' does not exist in this building, so there is nothing to report about it.",
        "This building has no radiation sensors.",
        "Based on the available data, the building does not track embodied carbon.",
    ],
)
async def test_a_true_absence_survives_untouched(answer: str) -> None:
    """Nothing is held for any of these, so the sentence is returned word for word."""
    out, changes = await sc.rewrite_false_existence(answer, HoldingReach())
    assert out == answer and changes == []


@pytest.mark.asyncio
async def test_a_reach_that_cannot_answer_leaves_the_sentence_alone() -> None:
    class Down(sc.Reach):
        async def holds(self, subject: str) -> Optional[sc.Held]:
            raise RuntimeError("graph unreachable")

    answer = "This building does not have occupancy sensors."
    out, changes = await sc.rewrite_false_existence(answer, Down())
    assert out == answer and changes == []


@pytest.mark.asyncio
async def test_a_rewrite_never_names_machinery() -> None:
    out, _ = await sc.rewrite_false_existence(
        "This building does not have occupancy sensors.",
        HoldingReach({"occupancy sensors": OCCUPANCY}),
    )
    for jargon in ("sparql", "lane", "intermediate_results", "ontology"):
        assert jargon not in out.lower()


# ── 3. what is never reached ────────────────────────────────────────────────────────────────────


def a_state(**results: Any) -> SimpleNamespace:
    return SimpleNamespace(intermediate_results=dict(results), user_message="")


CLAIM = "This building does not have occupancy sensors."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "results, lane, question",
    [
        ({"privacy_refusal_result": {"formatted_response": "x"}}, "metadata", "how busy is it?"),
        ({"control_result": {"message": "x"}}, "metadata", "how busy is it?"),
        ({"observability_result": {"formatted_response": "x"}}, "metadata", "how busy is it?"),
        ({"disclosure_decision": {"refused": True}}, "metadata", "how busy is it?"),
        ({}, "control", "how busy is it?"),
        ({}, "privacy_refusal", "how busy is it?"),
        ({}, "metadata", "who is in the lobby right now, and where is she going?"),
    ],
)
async def test_privacy_control_and_observability_results_are_never_rewritten(
    results: Dict[str, Any], lane: str, question: str
) -> None:
    reach = HoldingReach({"occupancy sensors": OCCUPANCY})
    out, changes = await sc.correct_false_existence(
        a_state(**results), CLAIM, lane, question, reach
    )
    assert out == CLAIM and changes == [] and reach.asked == []


@pytest.mark.asyncio
async def test_a_not_measured_statement_is_never_rewritten() -> None:
    answer = (
        "Radiation is not measured in this building, so this building has no radiation sensors."
    )
    reach = HoldingReach()
    out, changes = await sc.correct_false_existence(
        a_state(), answer, "sensor_data", "how much radiation is there?", reach
    )
    assert out == answer and changes == [] and reach.asked == []


@pytest.mark.asyncio
async def test_the_referent_gates_own_refusal_is_examined_but_only_rewritten_when_false() -> None:
    """It is upstream and its sentence is what a reader must not be told falsely."""
    gate = "'car parking' does not exist in this building, so there is nothing to report about it."
    state = a_state(referent_refusal_result={"formatted_response": gate})
    held, _ = await sc.correct_false_existence(
        state, gate, "analytics", "car parking is eligible", HoldingReach({"car parking": PARKING})
    )
    assert "does not exist" not in held
    kept, _ = await sc.correct_false_existence(
        state, gate, "analytics", "is there a swimming pool", HoldingReach()
    )
    assert kept == gate


@pytest.mark.asyncio
async def test_an_answer_with_no_claim_costs_no_graph_read() -> None:
    reach = HoldingReach()
    out, changes = await sc.correct_false_existence(
        a_state(), "Floor 3 averaged 780 ppm.", "sensor_data", "co2 on floor 3?", reach
    )
    assert out == "Floor 3 averaged 780 ppm." and changes == [] and reach.asked == []


@pytest.mark.asyncio
async def test_the_hook_records_what_it_changed_on_the_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    async def sparql_exec(query: str) -> Dict[str, Any]:
        return {"results": {"bindings": []}}

    async def fake_holds(self: Any, subject: str) -> Optional[sc.Held]:
        return OCCUPANCY if "occupancy" in subject else None

    monkeypatch.setattr(sc.GraphReach, "holds", fake_holds)
    state = a_state(original_query="Is there anyone in the lobby?")
    out = await sc.apply_to_answer(
        state, CLAIM, lane="metadata", sparql_exec=sparql_exec, namespace="urn:bldg#"
    )
    assert "does not have occupancy sensors" not in out
    assert state.intermediate_results["false_existence"][0]["held"] == "occupancy"


# ── 4. a modifier is not decoration ─────────────────────────────────────────────────────────────


def _parking_exec() -> Any:
    async def run(query: str) -> Dict[str, Any]:
        return {
            "results": {
                "bindings": [
                    {
                        "s": {"value": "urn:bldg#Amenity_Parking"},
                        "l": {"value": "Ground Level Parking — Abacws Building"},
                        "cls": {"value": "http://ontosage.org/capabilities#ParkingArea"},
                    }
                ]
            }
        }

    return run


@pytest.mark.asyncio
async def test_an_amenity_is_held_only_when_every_content_word_is_accounted_for() -> None:
    """ "underground parking" is a TRUE absence: the building's parking is at ground level."""
    reach = sc.GraphReach(_parking_exec(), "urn:bldg#", "bldg1")
    assert await reach._held_amenity("underground parking") is None
    held = await reach._held_amenity("parking")
    assert held is not None and held.label == "Ground Level Parking"
    assert await reach._held_amenity("ground level parking") is not None


@pytest.mark.asyncio
async def test_a_device_word_is_not_the_head_of_an_amenity_claim() -> None:
    """ "radiation sensors" is about radiation; matching "sensor" would name a soil-moisture point."""
    reach = sc.GraphReach(_parking_exec(), "urn:bldg#", "bldg1")
    assert await reach._held_amenity("radiation sensors") is None
