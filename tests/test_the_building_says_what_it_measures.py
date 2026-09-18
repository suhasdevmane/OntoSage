# -*- coding: utf-8 -*-
"""A supervisor is never told the building lacks something it has (BUG-680/681/682).

* BUG-680 — the automation-capability answer decided whether a sensor existed from six Brick
  class names written into the orchestrator, one of which (Noise_Level_Sensor) Brick does not
  define, and promised a notification whatever the building had configured. A building that
  measures noise was told it had no noise sensor.
* BUG-681 — the sensor-type decline suggested "temperature, humidity, CO₂, air quality, water
  flow, or pressure" to every building.
* BUG-682 — agent memory recorded the co-reference rewrite as the question the user asked.

Also here, because they are the same defect in the same file: the modality repair must not
re-answer a typed absence with room sensors; the BUG-152 occupancy/energy check derives its
classes from the building's own declarations; the open "what is measured?" menu lists what is
counted, not what is declared; role-aware services are told who is reading.

Everything is offline: the graph, the counts and the channels are fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from orchestrator.workflow import _orchestrator as mod
from shared.models import ConversationState, Message

pytestmark = pytest.mark.unit


def _run(coro):
    return asyncio.run(coro)


def _orch() -> "mod.WorkflowOrchestrator":
    return mod.WorkflowOrchestrator.__new__(mod.WorkflowOrchestrator)


def _state(question: str, role="facility_manager") -> ConversationState:
    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=question,
        messages=[Message(role="user", content=question)],
    )
    s.intermediate_results["user_role"] = role
    return s


def _spec(name, classes, scope="room"):
    from orchestrator.services.deliberation.coverage_audit import ModalitySpec

    return ModalitySpec(name=name, brick_classes=list(classes), sat={"scope": scope})


_SPECS = [
    _spec("noise", ["Sound_Level_Sensor", "Noise_Level_Sensor"]),
    _spec("co2", ["CO2_Level_Sensor"]),
    _spec("water_flow", ["Water_Meter"], scope="floor"),
]


@pytest.fixture(autouse=True)
def _clean_cache():
    for name in ("_MEASURED_COUNTS_CACHE", "_MEASURED_COUNTS_PENDING"):
        getattr(mod, name, {}).clear()
    yield
    for name in ("_MEASURED_COUNTS_CACHE", "_MEASURED_COUNTS_PENDING"):
        getattr(mod, name, {}).clear()


@pytest.fixture
def building(monkeypatch):
    """Declared modalities, measured counts and delivering channels, all replaceable."""
    from orchestrator.services.deliberation import coverage_audit

    monkeypatch.setattr(coverage_audit, "load_modalities", lambda _b=None, **_k: list(_SPECS))
    box = SimpleNamespace(counts={"noise": 12, "co2": 40, "water_flow": 6}, delivers=True)

    async def _counts(timeout_s, building_id=None, **_k):
        return None if box.counts is None else dict(box.counts)

    monkeypatch.setattr(mod, "_measured_modality_counts", _counts, raising=False)
    monkeypatch.setattr(
        mod, "_notification_delivery_configured", lambda _b=None: box.delivers, raising=False
    )
    return box


def _automation(question: str, role="facility_manager"):
    state = _state(question, role)
    _run(_orch()._automation_capability_check_node(state))
    return (
        state.intermediate_results["dialogue_response"],
        state.intermediate_results["automation_capability_result"],
    )


NOISE_Q = "Can the building automatically alert me when noise gets too high?"
LACKS = "I don't have a dedicated sensor for"


# ── BUG-680: the automation answer ────────────────────────────────────────────


class TestAutomationDecidesFromTheBuilding:
    def test_a_building_that_measures_noise_is_not_told_it_lacks_a_noise_sensor(self, building):
        text, result = _automation(NOISE_Q)
        assert LACKS not in text
        assert result["sensor_available"] is True
        assert "Yes" in text and "12 sensor point(s)" in text

    def test_a_building_without_noise_is_told_so(self, building):
        building.counts = {"noise": 0, "co2": 40, "water_flow": 6}
        text, result = _automation(NOISE_Q)
        assert result["sensor_available"] is False
        assert LACKS in text
        assert "This building does measure: co2, water flow" in text

    def test_a_floor_scoped_quantity_is_found_too(self, building):
        """The room coverage matrix cannot see a per-floor meter; the count can."""
        text, result = _automation("Can you alert me automatically when water flow spikes?")
        assert result["sensor_available"] is True
        assert LACKS not in text

    def test_a_graph_read_failure_is_could_not_check_never_absent(self, building):
        building.counts = None
        text, result = _automation(NOISE_Q)
        assert result["sensor_available"] is None
        assert LACKS not in text
        assert "couldn't check" in text

    def test_one_unreadable_count_is_could_not_check(self, building):
        building.counts = {"noise": None, "co2": 40, "water_flow": 6}
        text, result = _automation(NOISE_Q)
        assert result["sensor_available"] is None
        assert LACKS not in text

    def test_an_unidentified_quantity_is_not_reported_absent(self, building):
        text, result = _automation("Can the building automatically do something when it's odd?")
        assert result["sensor_available"] is None
        assert LACKS not in text

    def test_no_hardcoded_class_decides_any_more(self):
        import inspect

        src = inspect.getsource(mod.WorkflowOrchestrator._automation_capability_check_node)
        assert "_KNOWN_SENSOR_CLASSES" not in src
        assert "_KW_MAP" not in src
        assert '"brick:Noise_Level_Sensor"' not in src
        assert "notify_available = True" not in src


class TestNotificationIsOnlyPromisedWhenConfigured:
    def test_no_channel_means_no_alert_is_promised(self, building):
        building.delivers = False
        text, result = _automation(NOISE_Q)
        assert result["notify_available"] is False
        assert "send you a personalised alert" not in text
        assert "Want me to create an alert rule" not in text
        assert "No notification channel is set up" in text

    def test_a_delivering_channel_is_offered(self, building):
        text, result = _automation(NOISE_Q)
        assert result["notify_available"] is True
        assert "send you a personalised alert" in text

    def test_no_channel_and_no_sensor_still_says_neither_is_available(self, building):
        building.delivers = False
        building.counts = {"noise": 0, "co2": 40, "water_flow": 6}
        text, _ = _automation(NOISE_Q)
        assert LACKS in text
        assert "No notification channel is set up" in text
        assert "Alerts can be set" not in text

    def test_the_remediation_for_a_missing_channel_is_admin_only(self, building):
        building.delivers = False
        assert "channels.yaml" not in _automation(NOISE_Q, "facility_manager")[0]
        assert "channels.yaml" in _automation(NOISE_Q, "admin")[0]


class TestDeliveryIsReadFromTheChannelConfig:
    def _svc(self, monkeypatch, channels):
        from orchestrator.services import notification_service as ns

        svc = ns.NotificationService("bx", _channels_override=channels)
        monkeypatch.setattr(ns, "get_notification_service", lambda _b=None: svc)

    def test_only_the_built_in_log_channel_delivers_nothing(self, monkeypatch):
        self._svc(monkeypatch, [{"id": "log", "type": "log", "enabled": True}])
        assert mod._notification_delivery_configured("bx") is False

    def test_a_placeholder_smtp_channel_delivers_nothing(self, monkeypatch):
        self._svc(monkeypatch, [{"id": "log", "type": "log"}, {"id": "m", "type": "smtp"}])
        assert mod._notification_delivery_configured("bx") is False

    def test_an_enabled_webhook_delivers(self, monkeypatch):
        self._svc(monkeypatch, [{"id": "w", "type": "webhook", "enabled": True}])
        assert mod._notification_delivery_configured("bx") is True

    def test_a_disabled_webhook_does_not(self, monkeypatch):
        self._svc(monkeypatch, [{"id": "w", "type": "webhook", "enabled": False}])
        assert mod._notification_delivery_configured("bx") is False

    def test_an_unreadable_config_promises_nothing(self, monkeypatch):
        from orchestrator.services import notification_service as ns

        def _boom(_b=None):
            raise RuntimeError("config unreadable")

        monkeypatch.setattr(ns, "get_notification_service", _boom)
        assert mod._notification_delivery_configured("bx") is False


# ── the counts themselves ─────────────────────────────────────────────────────


def _count_exec(counts, fail=False):
    """A SPARQL executor answering absence_guard's COUNT query from a {class: n} table."""

    async def _exec(query):
        if fail:
            raise ConnectionError("graph down")
        n = sum(v for cls, v in counts.items() if f'"{cls}"' in query)
        return {"results": {"bindings": [{"n": {"value": str(n)}}]}}

    return _exec


class TestMeasuredModalityCounts:
    def test_counts_every_declared_modality_in_every_scope(self):
        exec_ = _count_exec({"Sound_Level_Sensor": 5, "Water_Meter": 3})
        counts = _run(
            mod._measured_modality_counts(
                5.0, building_id="bx", namespace="urn:bx#", sparql_exec=exec_, specs=_SPECS
            )
        )
        assert counts == {"noise": 5, "co2": 0, "water_flow": 3}
        assert mod._measured_names(counts) == ["noise", "water flow"]

    def test_an_unreadable_graph_is_none_and_is_not_cached(self):
        counts = _run(
            mod._measured_modality_counts(
                5.0,
                building_id="bx",
                namespace="urn:bx#",
                sparql_exec=_count_exec({}, fail=True),
                specs=_SPECS,
            )
        )
        assert counts is None
        assert mod._MEASURED_COUNTS_CACHE == {}
        assert mod._measured_names(counts) == []

    def test_a_complete_result_is_cached_for_the_boot(self):
        calls = []

        async def _exec(query):
            calls.append(query)
            return {"results": {"bindings": [{"n": {"value": "1"}}]}}

        kw = dict(building_id="bx", namespace="urn:bx#", sparql_exec=_exec, specs=_SPECS)
        _run(mod._measured_modality_counts(5.0, **kw))
        first = len(calls)
        _run(mod._measured_modality_counts(5.0, **kw))
        assert first == len(_SPECS) and len(calls) == first

    def test_a_timeout_is_none_not_zero(self):
        async def _slow(query):
            await asyncio.sleep(2)
            return {"results": {"bindings": [{"n": {"value": "1"}}]}}

        counts = _run(
            mod._measured_modality_counts(
                0.05, building_id="bx", namespace="urn:bx#", sparql_exec=_slow, specs=_SPECS
            )
        )
        assert counts is None


# ── BUG-681: the sensor-type decline ──────────────────────────────────────────


def _gate(monkeypatch, counts):
    async def _counts(timeout_s, building_id=None, **_k):
        return counts

    monkeypatch.setattr(mod, "_measured_modality_counts", _counts, raising=False)

    async def _zero(_q):
        return {"results": {"bindings": [{"n": {"value": "0"}}]}}

    o = _orch()
    o.sparql_agent = SimpleNamespace(_execute_query=_zero)
    return _run(o._absent_sensor_type_message("How many radon sensors are there?"))


class TestTheDeclineSuggestsWhatTheBuildingMeasures:
    def test_it_suggests_exactly_the_measured_quantities(self, monkeypatch):
        text = _gate(monkeypatch, {"noise": 3, "co2": 5, "damper_position": 0})
        assert "radon sensors" in text
        assert "e.g. co2, noise —" in text
        assert "damper position" not in text
        assert "water flow, or pressure" not in text

    def test_the_suggestion_is_omitted_when_coverage_is_unavailable(self, monkeypatch):
        text = _gate(monkeypatch, None)
        assert "radon sensors" in text
        assert "e.g." not in text
        assert "temperature" not in text
        assert "Ask about a sensor type it has, or ask" in text

    def test_the_decline_speaks_plainly(self, monkeypatch):
        assert "ontology" not in _gate(monkeypatch, None).lower()


# ── BUG-682: agent memory records what was typed ──────────────────────────────


class TestMemoryRecordsTheTypedWording:
    def test_the_typed_wording_wins_over_a_rewrite(self):
        state = ConversationState(
            conversation_id="c",
            user_id="u",
            user_message="how about there?",
            messages=[
                Message(role="user", content="CO2 in room 5.01?"),
                Message(role="assistant", content="820 ppm"),
                Message(
                    role="user",
                    content="What is the humidity in room 5.01?",
                    metadata={"original_query": "how about humidity there?"},
                ),
                Message(role="assistant", content="41 %"),
            ],
        )
        assert mod._latest_typed_question(state) == "how about humidity there?"

    def test_without_a_rewrite_the_content_is_used(self):
        state = _state("What is the CO2 in room 5.01?")
        assert mod._latest_typed_question(state) == "What is the CO2 in room 5.01?"

    def test_the_memory_store_uses_it(self):
        import inspect

        src = inspect.getsource(mod.WorkflowOrchestrator._response_node)
        block = src[src.index("B.3: Store successful interaction") :]
        block = block[: block.index("store_failure")]
        assert "_latest_typed_question(state)" in block
        assert "messages[-2]" not in block.split("original_query =", 1)[1].split("\n", 1)[0]


# ── the modality repair never overrides a typed absence ──────────────────────


@pytest.fixture
def repair(monkeypatch):
    from orchestrator.services import modality_repair
    from orchestrator.services.deliberation import live

    ran = []

    async def _exec(query):
        ran.append(query)
        return {"results": {"bindings": [{"sensor": {"value": "urn:bx#Room_Temp_3.01"}}]}}

    monkeypatch.setattr(live, "sparql_exec", _exec)
    monkeypatch.setattr(modality_repair, "needs_repair", lambda *a, **k: True)
    monkeypatch.setattr(modality_repair, "needs_population", lambda *a, **k: False)
    monkeypatch.setattr(modality_repair, "build_modality_query", lambda *a, **k: "SELECT ?x {}")

    def run(result):
        o = _orch()
        o._infer_query_kind = lambda _t: "temperature"
        state = _state("What is the supply air temperature on floor 3?")
        _run(o._repair_retrieved_modality(state, result, "supply air temperature on floor 3"))
        return ran, result, state

    return run


def _empty(**extra):
    return {"success": True, "results": {"results": {"bindings": []}}, **extra}


class TestRepairLeavesATypedAbsenceAlone:
    def test_a_typed_absence_is_not_repaired(self, repair):
        result = _empty(method="typed_absence", retrieval_outcome={"outcome": "not_declared"})
        ran, result, state = repair(result)
        assert ran == []
        assert result["results"] == {"results": {"bindings": []}}
        assert "modality_repair" not in state.intermediate_results

    def test_an_ordinary_empty_result_is_still_repaired(self, repair):
        ran, result, state = repair(_empty())
        assert len(ran) == 1
        assert result["results"]["results"]["bindings"]
        assert state.intermediate_results["modality_repair"]["reason"] == "wrong_modality"

    def test_the_sparql_node_calls_the_guarded_repair(self):
        import inspect

        src = inspect.getsource(mod.WorkflowOrchestrator._sparql_node)
        assert "await self._repair_retrieved_modality(state, result, _sparql_query)" in src


# ── BUG-152 site: classes from the building, not a list in the orchestrator ──


@pytest.fixture
def kind_check(monkeypatch):
    from orchestrator.agents import sparql_agent
    from orchestrator.services.deliberation import coverage_audit

    specs = [
        _spec("occupancy", ["Occupancy_Count_Sensor", "Occupancy_Sensor", "Motion_Sensor"]),
        _spec("energy_submeter", ["Electrical_Meter", "Energy_Sensor"], scope="floor"),
        _spec("electric_power", ["Electric_Power_Sensor", "Power_Sensor"], scope="floor"),
        _spec("noise", ["Sound_Level_Sensor"]),
    ]
    monkeypatch.setattr(coverage_audit, "load_modalities", lambda _b=None, **_k: list(specs))
    monkeypatch.setattr(sparql_agent, "_active_namespace", lambda: "urn:bx#")

    def run(keywords, counts=None, fail=False, concepts=None):
        seen = []

        async def _exec(query):
            seen.append(query)
            if fail:
                raise ConnectionError("graph down")
            n = sum(v for cls, v in (counts or {}).items() if f'"{cls}"' in query)
            return {"results": {"bindings": [{"n": {"value": str(n)}}]}}

        state = _state("what is the energy use this week?")
        if concepts:
            state.intermediate_results["concepts"] = concepts
        absent = _run(_orch()._kind_is_confirmed_absent(keywords, state, sparql_exec=_exec))
        return absent, seen

    return run


ENERGY_WORDS = {"energy", "power", "electricity", "kwh"}


class TestSensorKindAbsenceUsesTheBuildingsClasses:
    def test_the_classes_come_from_the_declared_modalities(self, kind_check):
        _, seen = kind_check(ENERGY_WORDS)
        (query,) = seen
        for cls in ("Electrical_Meter", "Energy_Sensor", "Electric_Power_Sensor", "Power_Sensor"):
            assert f'"{cls}"' in query
        for invented in ("Electrical_Energy_Sensor", "People_Count_Sensor"):
            assert invented not in query
        assert "Sound_Level_Sensor" not in query

    def test_zero_points_is_a_confirmed_absence(self, kind_check):
        assert kind_check(ENERGY_WORDS, counts={})[0] is True

    def test_a_power_sensor_alone_prevents_the_absence_claim(self, kind_check):
        assert kind_check(ENERGY_WORDS, counts={"Power_Sensor": 2})[0] is False

    def test_a_graph_failure_never_claims_absence(self, kind_check):
        assert kind_check(ENERGY_WORDS, fail=True)[0] is False

    def test_no_classes_means_no_claim_and_no_query(self, kind_check):
        absent, seen = kind_check({"footfall"})
        assert absent is False and seen == []

    def test_the_resolved_concept_widens_the_check(self, kind_check):
        concepts = [{"concept_id": "busyness", "brick_classes": ["ontosage:People_Counter"]}]
        absent, seen = kind_check({"footfall"}, counts={"People_Counter": 4}, concepts=concepts)
        assert absent is False and '"People_Counter"' in seen[0]

    def test_no_class_name_is_quoted_in_the_orchestrator_any_more(self):
        """Neither invented name may be used as a value; comments may still name the defect."""
        import inspect

        src = inspect.getsource(mod)
        for name in ("People_Count_Sensor", "Electrical_Energy_Sensor", "Noise_Level_Sensor"):
            assert f'"{name}"' not in src and f'"brick:{name}"' not in src


# ── the open "what is measured here?" menu ────────────────────────────────────


@pytest.fixture
def menu(monkeypatch):
    from orchestrator.services import forecast_skill
    from orchestrator.services.deliberation import capability_schema, coverage_audit

    monkeypatch.setattr(coverage_audit, "load_modalities", lambda _b=None, **_k: list(_SPECS))
    monkeypatch.setattr(forecast_skill, "is_skill_question", lambda _q: False)
    box = SimpleNamespace(spaces=[])

    async def _schema(*_a, **_k):
        return SimpleNamespace(spaces=box.spaces)

    monkeypatch.setattr(capability_schema, "build_schema", _schema)

    def run(counts, role="facility_manager"):
        async def _counts(timeout_s, building_id=None, **_k):
            return counts

        monkeypatch.setattr(mod, "_measured_modality_counts", _counts, raising=False)
        state = _state("What is measured in this building?", role)
        _run(_orch()._observability_node(state))
        return state.intermediate_results["observability_result"]["formatted_response"]

    run.box = box
    return run


class TestTheBuildingMenuListsWhatIsMeasured:
    def test_it_lists_counted_quantities_not_declared_ones(self, menu):
        text = menu({"noise": 4, "co2": 0, "water_flow": 2})
        assert "I can measure:** noise, water flow." in text
        assert "co2" not in text

    def test_unreadable_counts_fall_back_to_room_coverage(self, menu):
        menu.box.spaces = [SimpleNamespace(modalities={"co2": {"status": "present"}})]
        assert "I can measure:** co2." in menu(None)

    def test_unreadable_everything_is_not_reported_as_nothing(self, menu):
        text = menu(None)
        assert "Nothing is currently readable" not in text
        assert "couldn't read" in text

    def test_a_partly_unreadable_count_is_not_reported_as_nothing(self, menu):
        text = menu({"noise": 0, "co2": None, "water_flow": 0})
        assert "Nothing is currently readable" not in text

    def test_a_building_with_nothing_says_so_plainly(self, menu):
        text = menu({"noise": 0, "co2": 0, "water_flow": 0})
        assert "Nothing is currently readable" in text
        assert "ontology" not in text.lower()


# ── role-aware services are told who is reading ──────────────────────────────


class _Capture:
    def __init__(self, *a, **k):
        pass

    seen = []

    async def answer(self, question, now=None, for_admin=False):
        _Capture.seen.append(for_admin)
        return {"success": True, "formatted_response": "ok"}


@pytest.mark.parametrize("role,expected", [("admin", True), ("facility_manager", False)])
def test_the_register_lane_passes_the_reader(monkeypatch, role, expected):
    from orchestrator.services import compliance_register_service as crs

    _Capture.seen = []
    monkeypatch.setattr(crs, "ComplianceRegisterService", _Capture)
    _run(_orch()._register_node(_state("which inspections are overdue?", role)))
    assert _Capture.seen == [expected]


@pytest.mark.parametrize("role,expected", [("admin", True), ("occupant", False)])
def test_the_asset_state_lane_passes_the_reader(monkeypatch, role, expected):
    from orchestrator.services import asset_state_service as ass

    _Capture.seen = []
    monkeypatch.setattr(ass, "AssetStateService", _Capture)
    _run(_orch()._asset_state_node(_state("is the lift working?", role)))
    assert _Capture.seen == [expected]


@pytest.mark.parametrize("role,expected", [("admin", True), ("analyst", False)])
def test_the_spatial_lane_passes_the_reader(monkeypatch, role, expected):
    from orchestrator.agents import spatial_agent

    seen = []

    class _Agent:
        async def resolve(self, query, building_id, floor=None, for_admin=False):
            seen.append(for_admin)
            return "ok"

    monkeypatch.setattr(spatial_agent, "get_spatial_agent", lambda: _Agent())
    _run(_orch()._spatial_query_node(_state("how big is floor 2?", role)))
    assert seen == [expected]


@pytest.mark.parametrize("role,expected", [("admin", True), ("operator", False)])
def test_the_shared_referent_gate_passes_the_reader(monkeypatch, role, expected):
    from orchestrator.agents import sparql_agent
    from orchestrator.services import referent_resolver

    seen = []

    class _Resolver:
        def __init__(self, *_a):
            pass

        async def resolve(self, **kw):
            seen.append(kw.get("for_admin"))
            return SimpleNamespace(status="found")

    monkeypatch.setattr(referent_resolver, "ReferentResolver", _Resolver)
    monkeypatch.setattr(sparql_agent, "_active_namespace", lambda: "urn:bx#")
    _run(mod.apply_referent_gate(_state("floor 9 bookings", role), "floor 9", None, lane="t"))
    assert seen == [expected]


def test_the_sparql_node_gate_and_the_events_lane_pass_the_reader():
    import inspect

    sparql = inspect.getsource(mod.WorkflowOrchestrator._sparql_node)
    gate = sparql[sparql.index("ReferentResolver(self.sparql_agent._execute_query)") :]
    assert "for_admin=reader_is_admin_in(state)" in gate[:600]
    events = inspect.getsource(mod.WorkflowOrchestrator._events_node)
    assert "service.answer(question, for_admin=reader_is_admin_in(state))" in events


@pytest.mark.parametrize("role,expected", [("admin", True), ("facility_manager", False)])
def test_the_meter_boundary_line_passes_the_reader_and_no_truncated_question(
    monkeypatch, role, expected
):
    from orchestrator.services.evidence import meter_boundary

    seen = []

    async def _for_building(_ns, _exec):
        return {"m": object()}

    def _statement(hits, **kw):
        seen.append(kw)
        return "Boundary line"

    monkeypatch.setattr(meter_boundary, "for_building", _for_building)
    monkeypatch.setattr(meter_boundary, "match", lambda *a, **k: [])
    monkeypatch.setattr(meter_boundary, "statement", _statement)
    state = _state("Which floor used the most energy yesterday?", role)
    state.current_intent = "sensor_data"
    line = _run(_orch()._meter_boundary_line(state, "Floor 3 used 120 kWh."))
    assert line == "Boundary line"
    assert seen == [{"for_admin": expected}]


def test_the_unmodelled_guard_and_self_description_pass_the_reader():
    import inspect

    response = inspect.getsource(mod.WorkflowOrchestrator._response_node)
    call = response[response.index("await _unmodelled_guard(") :][:200]
    assert "for_admin=reader_is_admin_in(state)" in call
    describe = inspect.getsource(mod.WorkflowOrchestrator._self_description_node)
    call = describe[describe.index("= describe(") :][:300]
    assert "for_admin=reader_is_admin_in(state)" in call
