# -*- coding: utf-8 -*-
"""An answer that says the building holds nothing is looked at once more (row 2D-18).

The behaviour these pin, in the order the module decides them:

* an absence claim is RECOGNISED in the shapes the live answers actually used;
* an honest decline is NEVER reopened — a typed absence, the referent gate, "not measured",
  a privacy or control refusal, and a lane that is not a retrieval lane all pass through;
* the probe needs a clear margin, and a register the failing lane already read does not count;
* the reopen calls ONE lane, once, and keeps the original decline when that lane gives nothing
  grounded;
* a false universal that is not reopened is reworded into a scoped statement, never a jargon
  fallback, and never an invented one;
* the whole thing is idempotent and switched off by ABSENCE_SECOND_CHANCE=false.

Every lane call is a fake callable, so nothing here needs a service or a model.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pytest

from orchestrator.services import absence_second_chance as sc

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 19)


# ── fixtures that stand in for the graph ────────────────────────────────────────────────────────


class FakeRecord:
    """A ``record_registry.RecordClass`` as the probe reads one."""

    def __init__(self, local_name: str, label: str, instances: int, terms: Sequence[str]):
        self.local_name = local_name
        self.label = label
        self.instances = instances
        self.terms = tuple(terms)
        self.qualifiers: tuple = ()


#: The terms are the BUILDING'S, declared in its ontology, and the plurals matter: the register
#: selector matches whole words, so a declared "lock" does not match "locks". bldg1's own door
#: register declares neither, which is why the live selector misses this question — a vocabulary
#: gap, reported separately, and not something this module may paper over with a second scorer.
DOOR = FakeRecord(
    "DoorHardware",
    "Door and shutter hardware",
    16,
    ("door and shutter hardware", "shutter", "roller shutter", "maglock", "secure doors", "locks"),
)
WASTE = FakeRecord(
    "WasteCollectionPoint", "Waste collection point", 24, ("waste collection point", "bin", "waste")
)

DOOR_ROWS: List[Dict[str, Any]] = [
    {
        "record": "urn:dr/DR-010",
        "recordId": "DR-010",
        "label": "Level 2 lab corridor fire door",
        "recordStatus": "defective",
        "openingKind": "fire door",
        "recordOwner": "Estates Operations Manager",
    },
    {
        "record": "urn:dr/DR-015",
        "recordId": "DR-015",
        "label": "Basement tank room door",
        "recordStatus": "overdue",
        "openingKind": "secure door",
        "recordOwner": "Estates Operations Manager",
    },
    {
        "record": "urn:dr/DR-001",
        "recordId": "DR-001",
        "label": "Main entrance",
        "recordStatus": "active",
        "openingKind": "entrance",
        "recordOwner": "Estates Operations Manager",
    },
]

LIFT_TEXT = sc.TextHit(
    "urn:bldg#MainLift",
    "Main passenger lift",
    "http://www.w3.org/2000/01/rdf-schema#comment",
    "Weight limit 1000 kg. Door clear width 90 cm. Internal 106 x 220 cm.",
)
POLICY_TEXT = sc.TextHit(
    "urn:bldg#Cap_privacy",
    "Data Privacy",
    "http://ontosage.org/capabilities#answerText",
    # Long authored prose that happens to contain two of almost any question's words.
    "Your privacy is protected. The building does not track individual people. Maintenance of "
    "the scheduled access logs is handled by estates; task lists, rosters, retention windows, "
    "lawful basis, data subject rights, CCTV notices, visitor records and contractor inductions "
    "are all described in the building's published privacy policy, which is reviewed annually.",
)


class FakeReach(sc.Reach):
    """The three reads the probe makes, answered from fixtures."""

    def __init__(
        self,
        classes: Sequence[Any] = (DOOR, WASTE),
        rows: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        texts: Sequence[sc.TextHit] = (),
    ):
        self._classes = list(classes)
        self._rows = rows if rows is not None else {"DoorHardware": DOOR_ROWS}
        self._texts = list(texts)
        self.row_calls: List[Sequence[str]] = []

    async def classes(self) -> List[Any]:
        return self._classes

    async def rows(self, names: Sequence[str]) -> Dict[str, List[Dict[str, Any]]]:
        self.row_calls.append(list(names))
        return {n: self._rows[n] for n in names if n in self._rows}

    async def text_hits(self, topic: Sequence[str]) -> List[sc.TextHit]:
        stems = {sc.fold(t) for t in topic if len(t) >= 4}
        return [h for h in self._texts if sum(1 for s in stems if s in h.text.lower()) >= 2]


def a_state(**results: Any) -> SimpleNamespace:
    return SimpleNamespace(intermediate_results=dict(results), user_message="")


LOCKS_Q = "Which locks or secure doors have an owner-confirmed defect or overdue remedial action?"
LOCKS_A = (
    "The building's work-order register does not record any locks or secure doors that have an "
    "owner-confirmed defect, a temporary control, or an overdue remedial action.\n\n"
    "- The register contains 24 work-order records in total."
)


# ── 1. recognising an absence claim ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "answer, kind",
    [
        (LOCKS_A, "not_recorded"),
        ("The register does not record any information about slip hazards.", "not_recorded"),
        (
            "**This building doesn't keep a record of that.** What it does keep is…",
            "no_record_of_that",
        ),
        ("**No weekday/weekend comparison is available.** The supplied data gives…", "unavailable"),
        (
            "I'm sorry, but the data you retrieved only lists air-quality sensors and their "
            "locations.",
            "retrieval_only",
        ),
        (
            "There is no record in the building's database that describes a warden arrangement.",
            "no_information",
        ),
        ("I don't have that specific information on record for the building.", "none_on_record"),
    ],
)
def test_it_recognises_the_absence_shapes_the_live_answers_used(answer: str, kind: str) -> None:
    shape = sc.detect_absence_shape(answer)
    assert shape is not None and shape.kind == kind


@pytest.mark.parametrize(
    "answer",
    [
        "Floor 3 averaged 780 ppm of CO2 yesterday, from 42 sensors.",
        "There are no rooms above 25 degrees right now.",  # a RESULT SET, not an absence
        "",
    ],
)
def test_an_answer_that_is_not_an_absence_claim_is_left_alone(answer: str) -> None:
    assert sc.detect_absence_shape(answer) is None


def test_it_names_what_the_answer_said_was_missing() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    assert "locks" in shape.object_text and "secure doors" in shape.object_text


# ── 2. honest declines stay honest ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "results, lane, question, answer, expected",
    [
        (
            {"privacy_refusal_result": {"formatted_response": "x"}},
            "metadata",
            "q",
            LOCKS_A,
            "privacy",
        ),
        (
            {"referent_refusal_result": {"formatted_response": "x"}},
            "metadata",
            "q",
            LOCKS_A,
            "referent",
        ),
        (
            {"observability_result": {"formatted_response": "x"}},
            "metadata",
            "q",
            LOCKS_A,
            "observability",
        ),
        ({"control_result": {"message": "x"}}, "metadata", "q", LOCKS_A, "control"),
        ({"sparql_result": {"method": "typed_absence"}}, "metadata", "q", LOCKS_A, "typed absence"),
        ({}, "control", "q", LOCKS_A, "not a retrieval lane"),
        ({}, "floor_plan", "q", LOCKS_A, "not a retrieval lane"),
        (
            {},
            "metadata",
            "will data be collected on me by the building and used or sold?",
            LOCKS_A,
            "individuals",
        ),
        (
            {},
            "metadata",
            "how much radiation is there?",
            "Radiation is not measured in this building.",
            "not measured",
        ),
        (
            {},
            "metadata",
            "where is room 9.99?",
            "'Room 9.99' does not exist in this building, so there is nothing to report about it.",
            "does not exist",
        ),
    ],
)
def test_a_typed_or_deliberate_decline_is_never_reopened(
    results: Dict[str, Any], lane: str, question: str, answer: str, expected: str
) -> None:
    why = sc.skip_reason(results, lane, question, answer)
    assert why is not None and expected in why


@pytest.mark.asyncio
async def test_a_skipped_turn_records_why_and_changes_nothing() -> None:
    state = a_state(privacy_refusal_result={"formatted_response": "x"})
    assert (
        await sc.absence_second_chance(LOCKS_Q, LOCKS_A, "metadata", state, reach=FakeReach())
        is None
    )
    assert state.intermediate_results["second_chance"]["outcome"] == "skipped"


# ── 3. the probe ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_it_finds_the_register_the_failing_lane_never_read() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    found = await sc.probe(LOCKS_Q, shape, {}, FakeReach(), "metadata", TODAY)
    assert found and found[0].kind == "register" and found[0].name == "DoorHardware"
    assert found[0].tier == "A"
    assert "Door and shutter hardware" in found[0].evidence


@pytest.mark.asyncio
async def test_a_register_the_lane_already_read_is_not_offered_again() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    results = {"_prov_stores": [{"source_id": "ontosage:DoorHardware"}]}
    found = await sc.probe(LOCKS_Q, shape, results, FakeReach(), "metadata", TODAY)
    assert all(c.name != "DoorHardware" for c in found)


@pytest.mark.asyncio
async def test_only_the_shortlist_has_its_rows_read() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    reach = FakeReach()
    await sc.probe(LOCKS_Q, shape, {}, reach, "metadata", TODAY)
    assert len(reach.row_calls) == 1
    assert len(reach.row_calls[0]) <= sc.MAX_SHORTLIST


@pytest.mark.asyncio
async def test_a_question_with_nothing_to_go_on_produces_no_candidate() -> None:
    shape = sc.detect_absence_shape("The register does not record that.")
    assert shape is not None
    assert await sc.probe("what about it?", shape, {}, FakeReach(), "metadata", TODAY) == []


@pytest.mark.asyncio
async def test_long_authored_prose_is_not_a_leader_for_two_shared_words() -> None:
    """The density rule: a 300-word policy page shares words with everything and answers little."""
    answer = "**This building doesn't keep a record of that.**"
    shape = sc.detect_absence_shape(answer)
    assert shape is not None
    reach = FakeReach(classes=(), rows={}, texts=(POLICY_TEXT,))
    found = await sc.probe(
        "are there any maintenance tasks scheduled for today?", shape, {}, reach, "events", TODAY
    )
    assert all(c.tier != "A" for c in found)


@pytest.mark.asyncio
async def test_a_record_that_states_the_figure_asked_for_is_a_leader() -> None:
    answer = "The building's records do not contain a weight-limit value for the lifts."
    shape = sc.detect_absence_shape(answer)
    assert shape is not None
    reach = FakeReach(classes=(), rows={}, texts=(LIFT_TEXT, POLICY_TEXT))
    found = await sc.probe("What is the weight limit on the lifts?", shape, {}, reach, "metadata")
    assert found and found[0].payload is LIFT_TEXT and found[0].tier == "A"


def test_prose_is_only_reopened_when_the_question_asks_for_a_value() -> None:
    hits = [LIFT_TEXT]
    asked = sc.rank_text(["weight", "limit", "lift"], hits, set(), "What is the weight limit?")
    listed = sc.rank_text(["weight", "limit", "lift"], hits, set(), "Tell me about the lifts")
    assert asked and asked[0].tier == "A"
    assert all(c.tier != "A" for c in listed)


# ── 4. the one lane call ────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_grounded_lane_answer_replaces_the_decline_and_is_recorded() -> None:
    calls: List[str] = []

    async def answerer(candidate: sc.Candidate, question: str) -> str:
        calls.append(candidate.name)
        return "DR-010 is recorded as defective and DR-015 as overdue; owner: Estates."

    state = a_state()
    rep = await sc.absence_second_chance(
        LOCKS_Q,
        LOCKS_A,
        "metadata",
        state,
        reach=FakeReach(),
        answerers=sc.Answerers(register=answerer),
        today=TODAY,
    )
    assert rep is not None and rep.reopened and "DR-010" in rep.text
    assert calls == ["DoorHardware"], "exactly one lane, called once"
    assert rep.record()["outcome"] == "reopened"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "returned",
    [
        None,
        "",
        "The register does not record any locks or secure doors.",  # absence again
        "The data you provided does not include that.",  # meta-answer
        "The records lane returned nothing to report.",  # internal vocabulary
    ],
)
async def test_a_lane_that_gives_nothing_grounded_leaves_the_decline_standing(
    returned: Optional[str],
) -> None:
    async def answerer(candidate: sc.Candidate, question: str) -> Optional[str]:
        return returned

    state = a_state()
    rep = await sc.absence_second_chance(
        LOCKS_Q,
        LOCKS_A,
        "metadata",
        state,
        reach=FakeReach(),
        answerers=sc.Answerers(register=answerer),
        today=TODAY,
    )
    assert rep is None or not rep.reopened


@pytest.mark.asyncio
async def test_a_lane_that_raises_costs_nothing() -> None:
    async def answerer(candidate: sc.Candidate, question: str) -> str:
        raise RuntimeError("the register read timed out")

    rep = await sc.absence_second_chance(
        LOCKS_Q,
        LOCKS_A,
        "metadata",
        a_state(),
        reach=FakeReach(),
        answerers=sc.Answerers(register=answerer),
        today=TODAY,
    )
    assert rep is None or not rep.reopened


def test_the_register_answerer_is_the_register_lanes_own_composer() -> None:
    table = sc.RegisterTable("DoorHardware", "Door and shutter hardware", 3, DOOR_ROWS)
    candidate = sc.Candidate(
        "register", "DoorHardware", table.label, "A", 1.0, (), 1.0, 2.0, "", table
    )
    text = sc.register_answer(candidate, "Which doors are recorded as defective?", TODAY)
    assert "DR-010" in text and "DR-001" not in text
    assert "Read from all 3 of the building's Door and shutter hardware records" in text


def test_a_partially_read_register_never_states_a_count() -> None:
    table = sc.RegisterTable("DoorHardware", "Door and shutter hardware", 675, DOOR_ROWS)
    assert table.partial
    candidate = sc.Candidate(
        "register", "DoorHardware", table.label, "A", 1.0, (), 1.0, 2.0, "", table
    )
    text = sc.register_answer(candidate, "Which doors are recorded as defective?", TODAY)
    assert text == "", "a lookup over part of a register would state a wrong total"


def test_the_text_answerer_quotes_the_record_and_names_it() -> None:
    candidate = sc.Candidate(
        "text",
        LIFT_TEXT.subject,
        LIFT_TEXT.label,
        "A",
        1.0,
        ("weight", "limit"),
        1.0,
        2.0,
        "",
        LIFT_TEXT,
    )
    text = sc.text_answer(candidate, "What is the weight limit on the lifts?")
    assert "Weight limit 1000 kg." in text and "Main passenger lift" in text


# ── 4b. the sensor arm: what the building MEASURES ──────────────────────────────────────────────


class FakeSensor:
    """A ``sensor_binder.BoundSensor`` as this module reads one."""

    def __init__(self, uuid: str, label: str, quantity: str = "temperature"):
        self.uuid = uuid
        self.label = label
        self.quantity = quantity
        self.iri = f"urn:bldg#{label.replace(' ', '')}"
        self.storage = "bldg:timeseries"


class FakeBinding:
    """A ``sensor_binder.Binding``: bound to series, or a typed absence."""

    def __init__(self, sensors=(), quantity: str = "temperature", scope: str = "Room 1.06"):
        self.sensors = list(sensors)
        self.quantity_label = quantity
        self.display_scope = scope
        self.scope_label = scope
        self.basis = "own"
        self.status = "bound" if self.sensors else "absent"

    @property
    def is_bound(self) -> bool:
        return self.status == "bound" and bool(self.sensors)


BOUND = FakeBinding(
    [
        FakeSensor("u-1", "Room 1.06 temperature"),
        FakeSensor("u-2", "Room 1.06 window contact", "window_contact"),
    ]
)
ABSENT = FakeBinding([])

WINDOWS_Q = "Are my windows leaking heat right now?"
WINDOWS_A = (
    "The building's records do not contain any information about windows leaking heat. "
    "Please contact the facilities team."
)


class SensorReach(FakeReach):
    """A reach whose measurable() answer is fixed by the test."""

    def __init__(self, binding: Any, **kw: Any):
        super().__init__(**kw)
        self._binding = binding
        self.measurable_calls = 0

    async def measurable(self, question: str, results: Dict[str, Any]) -> Any:
        self.measurable_calls += 1
        return self._binding


@pytest.mark.asyncio
async def test_a_measured_quantity_is_found_when_a_record_lane_declined() -> None:
    shape = sc.detect_absence_shape(WINDOWS_A)
    assert shape is not None
    reach = SensorReach(BOUND, classes=(), rows={}, texts=())
    found = await sc.probe(WINDOWS_Q, shape, {}, reach, "sensor_data", TODAY)
    assert found and found[0].kind == "sensor" and found[0].tier == "A"
    assert "measures temperature" in found[0].evidence
    assert "2 series bound" in found[0].evidence


def test_a_building_wide_bind_is_not_described_as_a_place() -> None:
    """The binder calls a place-less scope "that place"; in an answer that reads as a room."""

    class Population(FakeBinding):
        def __init__(self) -> None:
            super().__init__([FakeSensor("u-9", "Room 0.01 occupancy", "occupancy")], "occupancy")
            self.basis = "population"
            self.scope_label = ""
            self.display_scope = "that place"

    candidate = sc.sensor_candidate(Population(), "are there free parking spaces now?")
    assert candidate is not None
    assert "that place" not in candidate.label and "that place" not in candidate.evidence
    assert candidate.label == "occupancy across the building"


@pytest.mark.asyncio
async def test_a_binder_typed_absence_is_believed_and_nothing_is_reopened() -> None:
    """The binder has established the place has none: the decline was RIGHT."""
    shape = sc.detect_absence_shape(WINDOWS_A)
    assert shape is not None
    reach = SensorReach(ABSENT, classes=(), rows={}, texts=())
    assert await sc.probe(WINDOWS_Q, shape, {}, reach, "sensor_data", TODAY) == []


@pytest.mark.asyncio
async def test_a_bound_series_outranks_a_register_that_merely_shares_words() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    reach = SensorReach(BOUND)
    found = await sc.probe(LOCKS_Q, shape, {}, reach, "metadata", TODAY)
    assert found[0].kind == "sensor", [c.kind for c in found]


@pytest.mark.asyncio
async def test_the_readings_lane_is_handed_the_series_and_its_answer_is_published() -> None:
    handed: List[List[str]] = []

    async def readings(candidate: sc.Candidate, question: str) -> str:
        handed.append([s.uuid for s in candidate.payload.sensors])
        return "Room 1.06 averaged 22.4 degC over the last hour, from 2 sensors."

    state = a_state()
    rep = await sc.absence_second_chance(
        WINDOWS_Q,
        WINDOWS_A,
        "sensor_data",
        state,
        reach=SensorReach(BOUND, classes=(), rows={}, texts=()),
        answerers=sc.Answerers(sensor=readings),
        today=TODAY,
    )
    assert rep is not None and rep.reopened and "22.4" in rep.text
    assert handed == [["u-1", "u-2"]], "the bound series, handed over once"


@pytest.mark.asyncio
async def test_when_the_readings_lane_declines_the_answer_says_the_building_measures_it() -> None:
    async def readings(candidate: sc.Candidate, question: str) -> None:
        return None  # the aggregate lane cannot answer this question shape

    state = a_state()
    rep = await sc.absence_second_chance(
        WINDOWS_Q,
        WINDOWS_A,
        "sensor_data",
        state,
        reach=SensorReach(BOUND, classes=(), rows={}, texts=()),
        answerers=sc.Answerers(sensor=readings),
        today=TODAY,
        searched="the records I searched",
    )
    assert rep is not None and not rep.reopened
    assert "does** measure temperature at Room 1.06" in rep.text
    assert "2 series" in rep.text
    assert "do not contain any information about windows" not in rep.text


@pytest.mark.asyncio
async def test_a_privacy_refusal_is_not_reopened_even_when_series_exist() -> None:
    """Every earlier guarantee survives the new arm."""
    state = a_state(privacy_refusal_result={"formatted_response": "x"})
    reach = SensorReach(BOUND, classes=(), rows={}, texts=())
    rep = await sc.absence_second_chance(
        "who is in room 1.06 right now?", WINDOWS_A, "sensor_data", state, reach=reach
    )
    assert rep is None and reach.measurable_calls == 0


@pytest.mark.asyncio
async def test_a_not_measured_decline_is_not_reopened() -> None:
    answer = "Radiation is not measured in this building."
    state = a_state()
    reach = SensorReach(BOUND, classes=(), rows={}, texts=())
    assert (
        await sc.absence_second_chance(
            "how much radiation is there?", answer, "sensor_data", state, reach=reach
        )
        is None
    )
    assert reach.measurable_calls == 0


# ── 5. the wording when it is not reopened ──────────────────────────────────────────────────────


def test_a_false_universal_becomes_a_scoped_statement_naming_the_closest_thing() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    closest = [
        sc.Candidate(
            "register", "DoorHardware", "Door and shutter hardware", "B", 1.0, (), 0.5, 1.0, ""
        )
    ]
    text = sc.reword_absence(LOCKS_A, shape, closest, "the building's work order records")
    assert text is not None
    assert "does not record any locks" not in text
    assert "I did not find" in text and "the building's work order records" in text
    assert "Door and shutter hardware records" in text
    assert (
        "- The register contains 24 work-order records in total." in text
    ), "the rest is untouched"


def test_a_pointer_is_never_an_internal_identifier() -> None:
    """The same rule the recurrence table was repaired for: no identifier printed at a reader."""
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    ident = sc.Candidate("text", "urn:x", "policy_facility_manager_any", "B", 1.0, (), 0.4, 1.0, "")
    assert not sc.useful_pointer(ident)
    text = sc.reword_absence(LOCKS_A, shape, [ident], "the records I searched")
    assert text is not None and "policy_facility_manager_any" not in text
    assert "I did not find" in text, "the false universal is still scoped away"


def test_a_scoped_statement_never_names_machinery() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    closest = [
        sc.Candidate(
            "register", "DoorHardware", "Door and shutter hardware", "B", 1.0, (), 0.5, 1.0, ""
        )
    ]
    text = sc.reword_absence(LOCKS_A, shape, closest, "")
    assert text is not None
    for jargon in ("sparql", "lane", "intermediate_results", "register lane", "retrieval"):
        assert jargon not in text.lower()


def test_an_already_scoped_decline_is_not_reworded() -> None:
    answer = "**The building's documents do not answer this.** I searched Fire Safety; …"
    shape = sc.detect_absence_shape(answer)
    assert shape is not None and not shape.reword
    closest = [
        sc.Candidate(
            "register", "DoorHardware", "Door and shutter hardware", "B", 1.0, (), 0.5, 1.0, ""
        )
    ]
    assert sc.reword_absence(answer, shape, closest, "") is None


def test_with_no_candidate_the_answer_is_returned_word_for_word() -> None:
    shape = sc.detect_absence_shape(LOCKS_A)
    assert shape is not None
    assert sc.reword_absence(LOCKS_A, shape, [], "the records I searched") is None


# ── 6. the flag, idempotence and the hook ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_flag_switches_the_whole_thing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(sc.ENV_FLAG, "false")
    state = a_state()
    assert (
        await sc.absence_second_chance(LOCKS_Q, LOCKS_A, "metadata", state, reach=FakeReach())
        is None
    )
    assert "second_chance" not in state.intermediate_results


@pytest.mark.asyncio
async def test_an_answer_that_answers_first_is_not_replaced_over_a_later_claim() -> None:
    """Measured: acting on a second-sentence claim swapped a good answer for a smaller lookup."""
    answer = (
        "There are 14 consumable items recorded in the building's stock register. Three are "
        "marked low: STK-08, STK-12 and STK-19.\n\n"
        "The register does not record a reorder date for any of them."
    )
    shape = sc.detect_absence_shape(answer)
    assert shape is not None and not shape.opens, "the answer answered first"
    called: List[str] = []

    async def answerer(candidate: sc.Candidate, question: str) -> str:
        called.append(candidate.name)
        return "2 of the 29 records in the Stock item register match."

    rep = await sc.absence_second_chance(
        "Which consumables are running low?",
        answer,
        "metadata",
        a_state(),
        reach=FakeReach(),
        answerers=sc.Answerers(register=answerer),
        today=TODAY,
    )
    assert called == [], "no lane is asked to rewrite an answer that already answered"
    assert rep is None or not rep.reopened


@pytest.mark.asyncio
async def test_an_absence_that_qualifies_a_real_answer_is_left_alone() -> None:
    """A good answer that ends with a true caveat is not a false absence, and is not touched."""
    answer = (
        "**Postings that require an owner check for coding**\n\n"
        "The register records that a coding check is required for three postings: CL-2026-011, "
        "CL-2026-019 and CL-2026-021. All 24 postings share the same financial period 2026-08.\n\n"
        "The register does not contain any fields for project, asset or activity coding."
    )
    shape = sc.detect_absence_shape(answer)
    assert shape is not None and not shape.leads, "the claim sits after the answer"
    state = a_state()
    rep = await sc.absence_second_chance(
        "Which postings need an owner check for coding?",
        answer,
        "metadata",
        state,
        reach=FakeReach(),
        answerers=sc.Answerers(register=lambda c, q: None),
        today=TODAY,
    )
    assert rep is None
    assert state.intermediate_results["second_chance"]["why"] == "the absence qualifies an answer"


@pytest.mark.asyncio
async def test_a_turn_is_looked_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    state = a_state(second_chance={"outcome": "reworded"})
    assert (
        await sc.absence_second_chance(LOCKS_Q, LOCKS_A, "metadata", state, reach=FakeReach())
        is None
    )
    assert state.intermediate_results["second_chance"] == {"outcome": "reworded"}


@pytest.mark.asyncio
async def test_the_hook_returns_the_answer_unchanged_when_it_cannot_look() -> None:
    state = a_state(original_query=LOCKS_Q)
    assert await sc.apply_to_answer(state, LOCKS_A, lane="metadata", sparql_exec=None) == LOCKS_A


@pytest.mark.asyncio
async def test_the_hook_reads_the_graph_and_rewrites_the_false_universal() -> None:
    async def sparql_exec(query: str) -> Dict[str, Any]:
        if "rdfs:comment" in query or "answerText" in query:
            return {"results": {"bindings": []}}
        return {
            "results": {
                "bindings": [
                    {
                        "record": {"value": r["record"]},
                        "p": {"value": f"http://ontosage.org/capabilities#{k}"},
                        "v": {"value": v},
                    }
                    for r in DOOR_ROWS
                    for k, v in r.items()
                    if k != "record"
                ]
            }
        }

    async def classes() -> List[Any]:
        return [DOOR, WASTE]

    state = a_state(original_query=LOCKS_Q)
    reach = sc.GraphReach(sparql_exec, "urn:bldg#")
    reach.classes = classes  # type: ignore[assignment]
    rep = await sc.absence_second_chance(
        LOCKS_Q,
        LOCKS_A,
        "metadata",
        state,
        reach=reach,
        answerers=sc.graph_answerers(TODAY),
        searched="the building's work order records",
        today=TODAY,
    )
    assert rep is not None
    assert "DR-010" in rep.text or "I did not find" in rep.text


def test_what_was_searched_is_named_from_the_turns_own_evidence() -> None:
    results = {"_prov_stores": [{"source_id": "ontosage:WorkOrder"}]}
    assert sc.searched_phrase(results) == "the building's work order records"
    assert sc.searched_phrase({}) == ""


def test_the_hook_is_wired_into_the_response_node() -> None:
    """Step 3 of .claude/rules/agent-patterns.md: a lane nobody collects answers nobody."""
    from pathlib import Path

    source = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
    assert "absence_second_chance import apply_to_answer" in source
    assert "final_response = await _second_chance(" in source


# ── 7. the bus carries _prov_stores in TWO shapes ───────────────────────────────────────────────


def test_prov_stores_are_read_in_both_shapes_the_bus_carries() -> None:
    """provenance.py writes raw store KEYS (str); the register lane writes dicts."""
    results = {
        "_prov_stores": [
            "graphdb",
            {"source_id": "ontosage:WorkspaceProfile", "kind": "authoritative"},
            None,
            {"kind": "no source id"},
        ]
    }
    assert sc.stored_sources(results) == ["graphdb", "ontosage:WorkspaceProfile", ""]
    assert sc.used_classes(results) == {"WorkspaceProfile"}
    assert sc.searched_phrase(results) == "the building's workspace profile records"
    assert sc.stored_sources({"_prov_stores": "not a list"}) == []


@pytest.mark.asyncio
async def test_a_turn_with_string_provenance_is_not_silently_skipped(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The live failure: the second look raised on a str store and went quiet on that path."""
    import logging

    async def sparql_exec(query: str) -> Dict[str, Any]:
        return {"results": {"bindings": []}}

    async def no_classes(self: Any) -> List[Any]:
        return [DOOR]

    monkeypatch.setattr(sc.GraphReach, "classes", no_classes)
    state = a_state(
        original_query=LOCKS_Q,
        _prov_stores=["graphdb", {"source_id": "ontosage:WorkspaceProfile"}],
    )
    with caplog.at_level(logging.WARNING):
        out = await sc.apply_to_answer(
            state, LOCKS_A, lane="metadata", sparql_exec=sparql_exec, namespace="urn:bldg#"
        )
    assert not [r for r in caplog.records if "[second_chance] skipped" in r.getMessage()]
    assert "second_chance" in state.intermediate_results, "the look ran and left its record"
    assert out


@pytest.mark.asyncio
async def test_a_skipped_look_names_the_line_that_failed(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    async def boom(*a: Any, **k: Any) -> None:
        raise AttributeError("'str' object has no attribute 'get'")

    monkeypatch.setattr(sc, "absence_second_chance", boom)
    state = a_state(original_query=LOCKS_Q)

    async def sparql_exec(query: str) -> Dict[str, Any]:
        return {}

    with caplog.at_level(logging.WARNING):
        out = await sc.apply_to_answer(state, LOCKS_A, lane="metadata", sparql_exec=sparql_exec)
    assert out == LOCKS_A, "fails safe: the answer goes out unchanged"
    message = next(
        r.getMessage() for r in caplog.records if "[second_chance] skipped" in r.getMessage()
    )
    assert "test_a_false_absence_gets_one_second_look.py:" in message, message
    assert " in boom" in message
