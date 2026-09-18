# -*- coding: utf-8 -*-
"""The workflow's own declines speak to the person reading them (2026-09-17, user decision).

`test_declines_speak_to_the_reader.py` holds the rule and the sites the DECLINES agent moved:
every reader keeps the honest decline and what IS available, in plain words; only a reader
whose authenticated role holds ``system:admin`` also sees how to add the data; an unknown role
is not an administrator.

Five more sites lived in `workflow/_orchestrator.py` and still told EVERY reader to add data:

* the locked data source — "Enable the X data source in the configuration panel";
* the deliberation lane, twice — "add the sensor (TTL + registered readings)";
* the anomaly lane — "adding it to the ontology and registering its readings";
* the automation-capability answer — "share the data source, I can register it", which also
  promised an action no chat turn can take.

Each is asked the same questions as the other sites: a non-admin sees the decline and no
remediation jargon, an admin sees the remediation, and the decline itself survives for both.

Also here, because it sits in the same lane: BUG-677, a class comparison that matched only
``ontosage:`` classes because Brick CURIEs kept their prefix.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message
from tests.test_declines_speak_to_the_reader import NON_ADMIN_ROLES, REMEDIATION_JARGON

pytestmark = pytest.mark.unit

#: The words these five sites used, on top of the shared list.
SITE_JARGON = REMEDIATION_JARGON + (
    "configuration panel",
    "data source",
    "registered readings",
    "register it",
    "registering",
)

READERS_WHO_ARE_NOT_ADMINS = NON_ADMIN_ROLES + (None, "", "guest")


def _assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in SITE_JARGON:
        assert word.lower() not in lowered, f"{word!r} reached a non-admin reader:\n{text}"


def _state(question: str, role) -> ConversationState:
    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=question,
        messages=[Message(role="user", content=question)],
    )
    if role is not None:
        s.intermediate_results["user_role"] = role
    return s


def _orch() -> "mod.WorkflowOrchestrator":
    return mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)


def _run(coro):
    return asyncio.run(coro)


# ── locked data source ───────────────────────────────────────────────────────


def _locked(role) -> str:
    o = _orch()
    spec = SimpleNamespace(
        provenance_system="Energy metering system",
        label="Energy meters",
        unlocks=["energy_use", "peak_demand"],
    )
    o.datasource_registry = SimpleNamespace(get=lambda sid: spec if sid == "energy" else None)
    state = _state("what was the energy use yesterday?", role)
    state.intermediate_results.update(locked_source="energy", locked_reason="disabled")
    _run(o._locked_capability_node(state))
    return state.intermediate_results["dialogue_response"]


VERDICT_LOCKED = "which is currently switched **off**, so I can't answer it."


class TestLockedDataSource:
    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, role):
        text = _locked(role)
        assert VERDICT_LOCKED in text
        _assert_plain(text)

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_still_sees_what_it_would_answer(self, role):
        text = _locked(role)
        assert "energy use" in text and "peak demand" in text

    def test_an_admin_sees_the_remediation(self):
        text = _locked("admin")
        assert VERDICT_LOCKED in text
        assert "Enable the **Energy meters** data source in the configuration panel" in text


# ── deliberation lane ────────────────────────────────────────────────────────


class _Modality(SimpleNamespace):
    pass


@pytest.fixture
def deliberation(monkeypatch):
    """The deliberation node with its building, compiler and schema replaced."""
    from orchestrator.services.deliberation import (
        capability_schema,
        clarify_policy,
        compiler,
        coverage_audit,
        live,
    )

    monkeypatch.setattr(
        live, "active_identity", lambda: {"BUILDING_ID": "bx", "BUILDING_NAMESPACE": "urn:bx#"}
    )
    monkeypatch.setattr(
        coverage_audit,
        "load_modalities",
        lambda _b=None: [_Modality(name="co2"), _Modality(name="zone_air_temperature")],
    )

    async def _compile(query, modalities):
        return SimpleNamespace(raw_query=query)

    async def _schema(*_a, **_k):
        return SimpleNamespace()

    monkeypatch.setattr(compiler, "compile_query", _compile)
    monkeypatch.setattr(capability_schema, "build_schema", _schema)

    # What the building SENSES is counted from the graph (BUG-663 shape, fixed with BUG-680),
    # so the fake supplies counts; a unit test must never reach the live graph for them.
    counts = {"co2": 3, "zone_air_temperature": 2}

    async def _counts(timeout_s, building_id=None, **_k):
        return dict(counts) if counts is not None else None

    monkeypatch.setattr(mod, "_measured_modality_counts", _counts)

    def run(role, *, unmapped: bool, measured=None, unreadable=False) -> str:
        nonlocal counts
        if unreadable:
            counts = None
        elif measured is not None:
            counts = dict(measured)
        if unmapped:
            monkeypatch.setattr(
                clarify_policy, "absorb_unmapped", lambda c: (c, ["radiation"], True)
            )
        else:
            monkeypatch.setattr(clarify_policy, "absorb_unmapped", lambda c: (c, [], False))
            monkeypatch.setattr(
                capability_schema,
                "validate",
                lambda c, s: SimpleNamespace(missing_modalities=["radiation"]),
            )
            monkeypatch.setattr(
                clarify_policy,
                "decide",
                lambda c, a: SimpleNamespace(
                    action="decline", assumptions=[], reason="", pending=None
                ),
            )
        state = _state("which room has the least radiation?", role)
        _run(_orch()._deliberate_node(state))
        return state.intermediate_results["deliberate_result"]["formatted_response"]

    return run


class TestDeliberationUnsensedTerm:
    VERDICT = "**'radiation' isn't something this building senses**, so I can't rank"

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, deliberation, role):
        text = deliberation(role, unmapped=True)
        assert self.VERDICT in text
        _assert_plain(text)

    def test_what_is_sensed_is_offered_in_plain_words(self, deliberation):
        text = deliberation("occupant", unmapped=True)
        assert "It does sense: co2, zone air temperature." in text

    def test_only_what_has_points_is_offered_as_sensed(self, deliberation):
        """Declared is not sensed: a modality with no point is not offered (BUG-663 shape)."""
        text = deliberation(
            "occupant", unmapped=True, measured={"co2": 3, "zone_air_temperature": 0}
        )
        assert "It does sense: co2." in text

    def test_unreadable_counts_offer_nothing_rather_than_the_declared_list(self, deliberation):
        text = deliberation("occupant", unmapped=True, unreadable=True)
        assert self.VERDICT in text
        assert "It does sense" not in text

    def test_an_admin_sees_the_remediation(self, deliberation):
        text = deliberation("admin", unmapped=True)
        assert self.VERDICT in text
        assert "TTL + registered readings" in text


class TestDeliberationMissingModality:
    VERDICT = "**No radiation sensors are modelled with data for this building**"

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, deliberation, role):
        text = deliberation(role, unmapped=False)
        assert self.VERDICT in text
        assert "what does this building monitor?" in text
        _assert_plain(text)

    def test_an_admin_sees_the_remediation(self, deliberation):
        text = deliberation("admin", unmapped=False)
        assert self.VERDICT in text
        assert "TTL + registered readings" in text


# ── anomaly lane ─────────────────────────────────────────────────────────────


def _anomaly(role) -> str:
    o = _orch()

    class _Detector:
        async def detect(self, state, message, sensor_data=None):
            return {"success": False, "anomalies": []}

    o.anomaly_agent = _Detector()
    state = _state("Is there a voltage fluctuation that could put our hardware at risk?", role)
    _run(o._anomaly_node(state))
    return state.intermediate_results["anomaly_result"]["formatted_response"]


class TestAnomalyNothingInstrumented:
    VERDICT = "This building has nothing instrumented for **voltage**"

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, role):
        text = _anomaly(role)
        assert self.VERDICT in text
        assert "not a fault" in text
        _assert_plain(text)

    def test_an_admin_sees_the_remediation(self):
        text = _anomaly("admin")
        assert self.VERDICT in text
        assert "adding it to the ontology and registering its readings" in text


# ── automation capability ────────────────────────────────────────────────────


@pytest.fixture
def automation(monkeypatch):
    """The automation-capability node over a FAKE building (BUG-680).

    Whether noise is measured is counted from the graph and whether an alert can be delivered
    is read from the channel config, so both are supplied here. Before BUG-680 this test ran
    with no fake at all, because the node decided from a class list in the orchestrator — and
    once it asked the graph, the unit test reached the live one and read 235 noise points.
    """
    from orchestrator.services.deliberation import coverage_audit
    from orchestrator.services.deliberation.coverage_audit import ModalitySpec

    monkeypatch.setattr(
        coverage_audit,
        "load_modalities",
        lambda _b=None, **_k: [
            ModalitySpec(name="noise", brick_classes=["Sound_Level_Sensor"]),
            ModalitySpec(name="co2", brick_classes=["CO2_Level_Sensor"]),
        ],
    )

    def run(role, *, noise_points: int = 0, delivers: bool = True) -> str:
        async def _counts(timeout_s, building_id=None, **_k):
            return {"noise": noise_points, "co2": 7}

        monkeypatch.setattr(mod, "_measured_modality_counts", _counts)
        monkeypatch.setattr(mod, "_notification_delivery_configured", lambda _b=None: delivers)
        state = _state("Can the building automatically alert me when noise gets too high?", role)
        _run(_orch()._automation_capability_check_node(state))
        return state.intermediate_results["dialogue_response"]

    return run


class TestAutomationWithoutASensor:
    VERDICT = "wired up in this building yet, so I can't set an alert on it."

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_sees_the_decline_and_no_remediation(self, automation, role):
        text = automation(role)
        assert self.VERDICT in text
        _assert_plain(text)

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS + ("admin",))
    def test_no_reader_is_promised_a_registration_the_chat_cannot_do(self, automation, role):
        assert "I can register it" not in automation(role)

    def test_an_admin_sees_the_remediation(self, automation):
        text = automation("admin")
        assert self.VERDICT in text
        assert "described in the ontology with registered readings" in text


class TestAutomationWithASensor:
    """The building DOES measure noise: never the decline, and still no jargon for non-admins."""

    VERDICT = TestAutomationWithoutASensor.VERDICT

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS + ("admin",))
    def test_no_reader_is_told_the_sensor_is_missing(self, automation, role):
        text = automation(role, noise_points=5)
        assert self.VERDICT not in text
        assert "noise" in text

    @pytest.mark.parametrize("role", READERS_WHO_ARE_NOT_ADMINS)
    def test_a_non_admin_without_a_channel_sees_no_remediation(self, automation, role):
        text = automation(role, noise_points=5, delivers=False)
        assert "No notification channel is set up" in text
        _assert_plain(text)
        assert "channels.yaml" not in text

    def test_an_admin_without_a_channel_sees_how_to_add_one(self, automation):
        text = automation("admin", noise_points=5, delivers=False)
        assert "No notification channel is set up" in text
        assert "channels.yaml" in text


# ── BUG-677: class names compared by local name ──────────────────────────────


@pytest.fixture
def modalities(monkeypatch):
    from orchestrator.services.deliberation import coverage_audit
    from orchestrator.services.deliberation.coverage_audit import ModalitySpec

    specs = [
        ModalitySpec(name="co2", brick_classes=["CO2_Level_Sensor"]),
        ModalitySpec(name="soil_moisture", brick_classes=["ontosage:Soil_Moisture_Sensor"]),
        ModalitySpec(name="rainfall", brick_classes=["Rainfall_Sensor"]),
    ]
    monkeypatch.setattr(coverage_audit, "load_modalities", lambda _b=None: list(specs))

    def ask(concept_classes):
        state = _state("is it stuffy in here?", "occupant")
        state.intermediate_results["concepts"] = [
            {"concept_id": "stuffy", "brick_classes": list(concept_classes)}
        ]
        return _run(_orch()._observability_modality("is it stuffy in here?", state))

    return ask


class TestClassNamesMatchByLocalName:
    def test_a_brick_curie_matches_a_bare_modality_class(self, modalities):
        """Failed before the fix: 'brick:co2_level_sensor' never equalled 'co2_level_sensor'."""
        assert modalities(["brick:CO2_Level_Sensor"]) == ("co2", "stuffy")

    def test_an_ontosage_curie_still_matches_a_prefixed_modality_class(self, modalities):
        assert modalities(["ontosage:Soil_Moisture_Sensor"])[0] == "soil_moisture"

    def test_an_ontosage_curie_matches_a_bare_modality_class(self, modalities):
        assert modalities(["ontosage:Rainfall_Sensor"])[0] == "rainfall"

    def test_a_full_iri_matches(self, modalities):
        assert modalities(["https://brickschema.org/schema/Brick#CO2_Level_Sensor"])[0] == "co2"

    def test_an_unrelated_class_matches_nothing(self, modalities):
        assert modalities(["brick:Luminance_Sensor"]) == (None, "")

    @pytest.mark.parametrize(
        "given",
        [
            "https://brickschema.org/schema/Brick#CO2_Sensor",
            "brick:CO2_Sensor",
            "ontosage:CO2_Sensor",
            "CO2_Sensor",
            " co2_sensor ",
        ],
    )
    def test_the_local_name_is_the_same_for_every_spelling(self, given):
        assert mod._class_local_name(given) == "co2_sensor"
