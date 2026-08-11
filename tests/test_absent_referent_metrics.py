# -*- coding: utf-8 -*-
"""Whole-building figures must not answer a question about a place that isn't there.

BUG-121. "How many sensors are in the swimming pool?" returned "Live building
figures for Abacws Building — Instrumented points: 533, Sensors declared: 326" for
a building with no pool. Every number was real; none of them answered the question,
and presenting them implied the pool exists and has 326 sensors.

The sparql node already gates named referents, but a metadata question routes to the
capability node FIRST, so its metrics responder ran before the gate was ever
reached. The same check now runs at that door too.

Gating is deliberately narrow: only a question that NAMES something is checked, so
"how many sensors are there?" keeps its whole-building answer. And it fails OPEN —
a resolver outage must not turn answerable questions into silence.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import orchestrator.agents.capability_agent as cap
import orchestrator.services.referent_resolver as rr
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit

_NAME = "Test Building"


def _state(message: str) -> ConversationState:
    return ConversationState(
        conversation_id="c1",
        user_id="u",
        user_message=message,
        building_id="bldgX",
        current_intent="metadata",
        messages=[Message(role="user", content=message)],
    )


def _resolver(monkeypatch, *, status: str, referent: str = "the swimming pool"):
    class _FakeResolver:
        def __init__(self, _exec):
            pass

        async def resolve(self, **_kw):
            return SimpleNamespace(status=status, referent=referent, message="")

    monkeypatch.setattr(rr, "ReferentResolver", _FakeResolver)
    monkeypatch.setattr(cap, "settings", SimpleNamespace(REFERENT_VALIDATION_ENABLED=True))


async def _decline(message: str):
    return await cap.CapabilityAgent._absent_referent_decline(_state(message), "bldgX", _NAME)


async def test_a_named_place_that_does_not_exist_is_declined(monkeypatch):
    _resolver(monkeypatch, status=rr.NOT_FOUND)
    out = await _decline("How many sensors are in the swimming pool?")

    assert out is not None, "a nonexistent place must not receive whole-building figures"
    assert out["provenance"] == "referent_not_found"
    assert "swimming pool" in out["response"]
    assert _NAME in out["response"]
    # It must not merely refuse — it must say how to make the question answerable.
    assert "ontology" in out["response"].lower()


async def test_a_named_place_that_exists_is_not_blocked(monkeypatch):
    _resolver(monkeypatch, status="found")
    assert await _decline("How many sensors are on floor 2?") is None


async def test_a_whole_building_question_is_never_gated(monkeypatch):
    """ "how many sensors are there?" names no place — the figures ARE the answer."""
    _resolver(monkeypatch, status=rr.NOT_FOUND)
    assert await _decline("How many sensors are there?") is None
    assert await _decline("How many sensors does this building have?") is None


# ── BUG-136: a check that cannot complete must not become "proceed" ──────────
# The original test here asserted the opposite — that a resolver error returns
# None so the question proceeds. That premise is what BUG-136 disproved: under
# back-to-back load the existence check timed out, SKIPPED sailed through, and
# "how many sensors are in the swimming pool?" was answered with whole-building
# figures. Failing open on a legitimate question loses one answer; failing open
# on an existence check produces a confident fabrication. The costs are not
# symmetrical, so neither is the behaviour.


async def test_a_skipped_check_for_a_named_place_refuses_to_assert(monkeypatch):
    _resolver(monkeypatch, status=rr.SKIPPED)
    out = await _decline("How many sensors are in the swimming pool?")

    assert out is not None, "SKIPPED must not silently become 'proceed'"
    assert out["provenance"] == "referent_unverified"
    assert "couldn't verify" in out["response"]
    assert "swimming pool" in out["response"]
    assert (
        "ask again" in out["response"]
    ), "must invite a retry — this is transient, not 'not found'"


async def test_a_resolver_error_for_a_named_place_refuses_to_assert(monkeypatch):
    class _Boom:
        def __init__(self, _exec):
            pass

        async def resolve(self, **_kw):
            raise RuntimeError("graphdb unreachable")

    monkeypatch.setattr(rr, "ReferentResolver", _Boom)
    monkeypatch.setattr(cap, "settings", SimpleNamespace(REFERENT_VALIDATION_ENABLED=True))

    out = await _decline("How many sensors are in the swimming pool?")
    assert out is not None and out["provenance"] == "referent_unverified"


async def test_a_question_naming_nothing_still_fails_open_on_error(monkeypatch):
    """The asymmetry cuts one way only: with nothing named there is nothing to
    fabricate about, so a broken resolver must not block whole-building answers."""

    class _Boom:
        def __init__(self, _exec):
            pass

        async def resolve(self, **_kw):
            raise RuntimeError("graphdb unreachable")

    monkeypatch.setattr(rr, "ReferentResolver", _Boom)
    monkeypatch.setattr(cap, "settings", SimpleNamespace(REFERENT_VALIDATION_ENABLED=True))

    assert await _decline("How many sensors are there?") is None


async def test_a_completed_check_is_unaffected_by_the_skip_handling(monkeypatch):
    _resolver(monkeypatch, status="resolved")
    assert await _decline("How many sensors are on floor 2?") is None


async def test_the_gate_respects_its_feature_flag(monkeypatch):
    _resolver(monkeypatch, status=rr.NOT_FOUND)
    monkeypatch.setattr(cap, "settings", SimpleNamespace(REFERENT_VALIDATION_ENABLED=False))
    assert await _decline("How many sensors are in the swimming pool?") is None


def test_the_gate_names_no_building():
    import inspect

    src = inspect.getsource(cap.CapabilityAgent._absent_referent_decline).lower()
    for literal in ("bldg1", "bldg2", "bldg3", "abacws", "buildsys", "swimming"):
        assert literal not in src, f"the gate must not name a building or a place: {literal}"


# ── which phrasings the gate can see at all ──────────────────────────────────


@pytest.mark.parametrize(
    "query,expected_token",
    [
        ("How many sensors are in the swimming pool?", "swimming|pool"),
        ("How many sensors are in the west wing?", "west|wing"),
        # Bare space nouns behind a determiner. Without these the gate was blind:
        # "on the helipad" was answered with the whole building's figures.
        ("How many sensors are on the helipad?", "helipad"),
        ("How many sensors are in the gym?", "gym"),
        ("Is there anything on the rooftop?", "rooftop"),
    ],
)
def test_named_spaces_are_visible_to_the_gate(query, expected_token):
    got = rr.detect_typed_referent(query)
    assert got is not None, f"gate cannot see the referent in: {query}"
    assert got.token == expected_token


def test_a_determiner_is_not_treated_as_a_modifier():
    """ "in the gym" once produced the token "the|gym", which demands an entity whose
    name contains BOTH words — so a gym the building really has was reported
    missing. The determiner must be dropped, not matched."""
    got = rr.detect_typed_referent("how many sensors are in the gym?")
    assert got.token == "gym"
    assert "the" not in got.token.split("|")


@pytest.mark.parametrize(
    "query",
    [
        "How many sensors are there?",
        "How many sensors does this building have?",
        "What is the temperature?",
    ],
)
def test_a_question_naming_no_place_is_invisible_to_the_gate(query):
    assert rr.detect_typed_referent(query) is None


def test_space_heads_are_generic_english_not_a_building_vocabulary():
    for head in rr._SPACE_HEADS:
        assert head.islower() and head.isalpha(), head
        assert not any(b in head for b in ("bldg", "abacws", "buildsys"))


# ── the gate covers the whole capability answer, not just its metrics branch ──


async def test_a_reading_question_about_an_absent_place_is_gated_before_any_source(monkeypatch):
    """Gating only the metrics branch was not enough: "what is the temperature on
    the rooftop helipad?" is not a metrics question, so it walked past the gate into
    the rest of the chain and came back with temperature values for a helipad the
    building does not have."""
    _resolver(monkeypatch, status=rr.NOT_FOUND, referent="rooftop helipad")
    out = await _decline("What is the temperature on the rooftop helipad?")
    assert out is not None
    assert out["provenance"] == "referent_not_found"


def test_the_gate_is_reached_for_measurement_questions_not_only_metrics_ones():
    """Guard the wiring: the decline must be considered whenever the question asks
    for a measurement, not only when it asks for a count or an area."""
    import inspect

    src = inspect.getsource(cap.CapabilityAgent.answer)
    assert "measurand_of" in src, "a reading question must reach the referent gate"
    gate = src.index("_absent_referent_decline")
    first_source = src.index("_is_metrics_question")
    assert gate > first_source - 400, "the gate must sit at the top of the chain"


# ── a specifically-named OTHER building must be gated (TODO-133 follow-up) ────
# Adding "air quality" to the data-query vocabulary made "air quality in Building
# 47" bypass the capability probe and answer with whole-building figures for a
# building that does not exist. The gate could not see it because there was no
# detector for "Building N" as a referent.


@pytest.mark.parametrize(
    "query,phrase",
    [
        ("What is the air quality in Building 47?", "building 47"),
        ("What is the temperature in Block C?", "block c"),
        ("What is the AQI in Tower 2?", "tower 2"),
    ],
)
def test_a_named_other_building_is_a_referent(query, phrase):
    got = rr.detect_typed_referent(query)
    assert got is not None, f"gate cannot see the other building in: {query}"
    assert got.phrase.lower() == phrase


@pytest.mark.parametrize(
    "query",
    [
        "What is the air quality in this building?",
        "how many sensors does the building have?",
        "air quality in the building right now",
    ],
)
def test_the_connected_building_is_not_treated_as_an_external_referent(query):
    """ "this/the building" mean the CONNECTED one — they must not be gated, or every
    whole-building question would decline."""
    got = rr.detect_typed_referent(query)
    assert got is None or got.head not in ("building", "block", "tower")


async def test_a_reading_question_about_another_building_is_declined(monkeypatch):
    _resolver(monkeypatch, status=rr.NOT_FOUND, referent="building 47")
    out = await _decline("What is the air quality in Building 47?")
    assert out is not None
    assert out["provenance"] == "referent_not_found"
