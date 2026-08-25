# -*- coding: utf-8 -*-
"""Can this building answer that? — the observability self-knowledge lane (V6-T10).

*"Can you measure formaldehyde in room 5.01?"* is a question about the SYSTEM'S REACH, not
about a reading, and answering it from prose is how BUG-192 happened: a model asserted a
building had no temperature sensors minutes after the same stack quoted one of their readings.

Four outcomes, deliberately distinct because they need four different actions from four
different people — and every negative names the step that would change it. "No" on its own
tells a facilities manager nothing they can act on.

The costliest direction is the one asserted throughout: **a value question must never be
answered with a reach answer.** Withholding data the building actually has is worse than the
gap it was protecting against.
"""

import pytest

from orchestrator.services.observability import (
    OBSERVABLE,
    STALE,
    UNCONNECTED,
    UNINSTRUMENTED,
    UNKNOWN,
    Reach,
    is_observability_question,
    present_modalities,
    reach_from_coverage,
)

pytestmark = pytest.mark.unit


# ── telling a reach question from a value question ───────────────────────────


class TestQuestionShape:
    @pytest.mark.parametrize(
        "q",
        [
            "Can you measure formaldehyde in room 5.01?",
            "can you monitor CO2 in 5.16?",
            "Do you have a noise sensor in the lab?",
            "Is room 5.01 instrumented for humidity?",
            "What can you measure in room 2.14?",
            "Where is lithium battery charging happening, and what detection covers it?",
            "what monitoring covers the plant room?",
            "Can you answer questions about air quality here?",
        ],
    )
    def test_reach_questions_are_recognised(self, q):
        assert is_observability_question(q), f"{q!r} would be answered from prose"

    @pytest.mark.parametrize(
        "q",
        [
            "What is the CO2 in room 5.01?",
            "how warm is it in 5.16?",
            "Where is the server room?",
            "show me floor 3",
            "how many people are in the building?",
            "How much energy did the building use last week?",
        ],
    )
    def test_value_and_location_questions_are_left_alone(self, q):
        """The costlier direction. Answering "what is the CO2 in 5.01?" with "yes, CO2 is
        measured there" withholds data the building has — a non-answer dressed as diligence."""
        assert not is_observability_question(q), f"{q!r} was claimed by the reach lane"


# ── the four outcomes ────────────────────────────────────────────────────────


class TestReachOutcomes:
    @pytest.mark.parametrize(
        "entry,expected",
        [
            ({"status": "present", "fresh": True}, OBSERVABLE),
            ({"status": "present", "fresh": False}, STALE),
            ({"status": "present", "fresh": None}, OBSERVABLE),
            ({"status": "unbacked"}, UNCONNECTED),
            ({"status": "missing"}, UNINSTRUMENTED),
            (None, UNINSTRUMENTED),
            ({"status": "something-new"}, UNKNOWN),
        ],
    )
    def test_coverage_maps_to_reach(self, entry, expected):
        assert reach_from_coverage("co2", "Room 5.01", entry).status == expected

    def test_unmeasured_freshness_is_not_reported_as_stale(self):
        """`fresh is None` means freshness could not be MEASURED. Reporting that as stale would
        downgrade every connected sensor in a building whose adapters were briefly unavailable
        — the degrade-to-a-legal-value failure, one layer up."""
        reach = reach_from_coverage("co2", "Room 5.01", {"status": "present", "fresh": None})
        assert reach.status == OBSERVABLE
        assert reach.fresh is None


# ── every negative names its unlock step ─────────────────────────────────────


class TestUnlockSteps:
    def test_uninstrumented_says_a_figure_would_be_invented(self):
        text = reach_from_coverage("formaldehyde", "Room 5.01", {"status": "missing"}).describe()
        assert "not measured" in text
        assert "invented" in text, "the answer does not say why it will not guess"
        assert "Unlock:" in text

    def test_unconnected_names_the_two_halves_of_contract_8(self):
        """A point described in the ontology with no rows behind it is a plumbing job, and the
        answer should say exactly which plumbing."""
        text = reach_from_coverage("co2", "Room 5.01", {"status": "unbacked"}).describe()
        assert "ref:hasTimeseriesId" in text and "ref:storedAt" in text
        assert "No code change" in text or "no code change" in text

    def test_stale_points_at_the_sensor_not_at_the_ontology(self):
        """Connected-but-silent is a different job from unconnected, and sending someone to
        edit a TTL when the instrument is dead wastes their afternoon."""
        text = reach_from_coverage(
            "co2", "Room 5.01", {"status": "present", "fresh": False, "stored_at": "co2_data"}
        ).describe()
        assert "not reported recently" in text
        assert "wiring is already in place" in text

    def test_observable_is_a_plain_yes(self):
        text = reach_from_coverage(
            "co2", "Room 5.01", {"status": "present", "fresh": True, "sensor": "http://x#S1"}
        ).describe()
        assert text.startswith("**Yes")
        assert "S1" in text, "the answer does not name its source"

    def test_unknown_says_it_cannot_tell_rather_than_saying_no(self):
        """The single most important branch. If the coverage picture cannot be built, "I don't
        know" and "it is not there" are opposite claims and only the first is true."""
        text = Reach(modality="co2", space_label="Room 5.01", status=UNKNOWN).describe()
        assert "can't tell you reliably" in text
        assert "guessing either way would be worse" in text

    def test_a_negative_offers_what_IS_measured_there(self):
        """ "We don't measure formaldehyde, but we do measure CO2 and PM2.5 here" is an answer
        somebody can act on."""
        text = reach_from_coverage(
            "formaldehyde",
            "Room 5.01",
            {"status": "missing"},
            present_modalities=["co2", "pm25", "humidity"],
        ).describe()
        assert "What IS measured there" in text
        assert "co2" in text


# ── what a space actually has ────────────────────────────────────────────────


def test_present_modalities_lists_only_connected_ones():
    """An unbacked point is not something the building can measure — offering it as an
    alternative would send the asker to a sensor with no readings."""
    got = present_modalities(
        {
            "co2": {"status": "present"},
            "humidity": {"status": "unbacked"},
            "noise": {"status": "missing"},
            "temperature": {"status": "present"},
        }
    )
    assert got == ["co2", "temperature"]


def test_present_modalities_is_empty_for_an_empty_space():
    assert present_modalities({}) == []


# ── wiring ───────────────────────────────────────────────────────────────────


class TestWiring:
    def test_the_intent_is_registered_with_a_node(self):
        from pathlib import Path

        import yaml

        doc = yaml.safe_load(
            Path("orchestrator/intents/intent_definitions.yaml").read_text(encoding="utf-8")
        )
        intents = doc.get("intents") or doc
        entry = next((i for i in intents if i.get("name") == "observability"), None)
        assert entry, "the observability intent is not registered"
        assert entry.get("node_method") == "_observability_node"

    def test_the_node_exists_on_the_orchestrator(self):
        from orchestrator.workflow._orchestrator import WorkflowOrchestrator

        assert hasattr(WorkflowOrchestrator, "_observability_node")

    def test_the_contract_routes_reach_questions_to_the_lane(self):
        from orchestrator.services.routing_contract import apply_contract

        for q in ("Can you measure formaldehyde in room 5.01?", "Do you have a noise sensor here?"):
            st = {"intent": "capability", "concepts": [], "entities": []}
            apply_contract(q, st, stage="parse")
            assert st["intent"] == "observability", f"{q!r} routed to {st['intent']}"

    def test_a_value_question_is_not_routed_to_the_lane(self):
        from orchestrator.services.routing_contract import apply_contract

        st = {"intent": "sensor_data", "concepts": [], "entities": []}
        apply_contract("What is the CO2 in room 5.01?", st, stage="parse")
        assert st["intent"] != "observability"

    def test_the_capability_probe_bypasses_reach_questions(self):
        from pathlib import Path

        src = Path("orchestrator/agents/dialogue_agent.py").read_text(encoding="utf-8")
        assert "is_observability_question as _is_observability_question" in src
        assert "not _is_observability_question(user_query)" in src

    def test_the_node_never_claims_absence_when_it_failed(self):
        """A lane that answers "not measured" because IT broke is worse than one that errors:
        the user acts on a false negative about their own building."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        start = src.index("async def _observability_node")
        rest = src[start + 30 :]
        # Bound at the next sibling method. A fixed-length slice measured the wrong region the
        # moment the node grew — the same measurement error that made a score assertion read
        # another method's numbers in V6-T26.
        ends = [
            i for i in (rest.find("\n    async def "), rest.find("\n    @staticmethod")) if i > 0
        ]
        body = rest[: min(ends)] if ends else rest
        assert "can't tell you reliably" in body
        assert "except Exception" in body

    def test_the_response_node_collects_the_lane_result(self):
        """A node that computes an answer nothing collects yields "I processed your request,
        but couldn't generate a response" — measured live before this dispatch entry existed.
        The node ran, the answer was correct, and no one saw it."""
        from pathlib import Path

        src = Path("orchestrator/workflow/_orchestrator.py").read_text(encoding="utf-8")
        assert 'get("observability_result")' in src
        assert '_observability_result["formatted_response"]' in src
