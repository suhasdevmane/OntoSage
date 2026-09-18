# -*- coding: utf-8 -*-
"""The last declines speak to the person reading them (2026-09-17, user decision).

``test_declines_speak_to_the_reader.py`` and ``test_remaining_declines_speak_to_the_reader.py``
pinned the decision on the services. Several CALLERS never passed the reader through, and a
handful of answers still told every reader about the implementation:

* "how old is this building?"      -> the capability agent called ``building_profile.render`` /
                                      ``enablement_hint`` with no role, so an administrator
                                      never saw how to add the fact
* "how do you know that?"          -> ``answer_provenance.render`` called with no role
* a multi-part plan's spatial step -> ``spatial_agent.resolve`` called with no role
* every energy figure              -> "no `ontosage:meterServes` in the ontology. Declaring the
                                      meter's boundary ..."
* "what can you do?"               -> "add a TTL describing the building and register a database"
* no readings for known sensors    -> "in the ontology ... the store they are registered to"
* a zero over an unmodelled class  -> "no such class in its ontology ... Adding them to the TTL"
* inventory and metrics footers    -> "(triples)", "Instrumented points in the ontology"
* an access denial                 -> "ask an administrator to register a policy"

The decision, as before: every reader keeps the HONEST DECLINE (design contract 4) and what IS
available; only a reader whose authenticated role holds ``system:admin`` also sees how to fix
it; an unknown or missing role is not an administrator.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

#: Words that only make sense to someone editing the building's data or its configuration.
JARGON = (
    "TTL",
    "triples",
    "ontology",
    "ontosage:",
    "brick:",
    "meterServes",
    "upload",
    "ingest",
    "register a",
    "registered",
    "declaring",
    "database1",
    "SPARQL",
    "yearBuilt",
    "admin console",
    "have not been loaded",
)

UNKNOWN_ROLES = (None, "", "guest", "superuser", "facility_manager", 7)


def _assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in JARGON:
        assert word.lower() not in lowered, f"{word!r} reached a non-admin reader:\n{text}"


def _as_admin(role) -> bool:
    from orchestrator.services.grounding_guard import reader_is_admin

    return reader_is_admin(role)


def _state(msg: str, role):
    from shared.models import ConversationState, Message

    s = ConversationState(
        conversation_id="c",
        user_id="u",
        user_message=msg,
        building_id="bldg1",
        current_intent="capability",
        messages=[Message(role="user", content=msg)],
    )
    if role is not None:
        s.intermediate_results["user_role"] = role
    return s


# ── 1a. the capability agent passes the reader to the building profile ─────────


class TestBuildingProfileCaller:
    def _wire(self, monkeypatch, profile):
        import orchestrator.agents.sparql_agent as sa
        from orchestrator.services import building_profile as bp

        class _NoSparql:
            async def _execute_query(self, _q):
                return {}

        async def _resolve(_ns, _exec):
            return profile

        monkeypatch.setattr(sa, "SPARQLAgent", _NoSparql)
        monkeypatch.setattr(sa, "_active_namespace", lambda: "http://example.org/b#")
        monkeypatch.setattr(bp, "resolve", _resolve)

    async def _answer(self, role, profile, monkeypatch):
        from orchestrator.agents.capability_agent import CapabilityAgent

        self._wire(monkeypatch, profile)
        state = _state("How old is this building?", role)
        return await CapabilityAgent._building_profile_answer("b", "Test Building", state)

    async def test_a_building_stating_nothing_declines_plainly_to_a_manager(self, monkeypatch):
        from orchestrator.services import building_profile as bp

        res = await self._answer("facility_manager", bp.BuildingProfile(resolved=True), monkeypatch)
        assert res["provenance"] == "building_profile_absent"
        assert "doesn't record" in res["response"] and "won't guess" in res["response"]
        _assert_plain(res["response"])

    async def test_a_building_stating_nothing_tells_an_admin_what_to_add(self, monkeypatch):
        from orchestrator.services import building_profile as bp

        res = await self._answer("admin", bp.BuildingProfile(resolved=True), monkeypatch)
        assert "doesn't record" in res["response"]
        assert "yearBuilt" in res["response"] and "TTL" in res["response"]

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_decline(self, monkeypatch, role):
        from orchestrator.services import building_profile as bp

        res = await self._answer(role, bp.BuildingProfile(resolved=True), monkeypatch)
        _assert_plain(res["response"])

    def _partial(self):
        from orchestrator.services import building_profile as bp

        return bp.BuildingProfile(facts={"Owner": "Acme"}, facets={"owner": "Acme"}, resolved=True)

    async def test_a_missing_facet_reaches_an_admin_with_the_remedy(self, monkeypatch):
        res = await self._answer("admin", self._partial(), monkeypatch)
        assert "Owner" in res["response"] and "TTL" in res["response"]

    async def test_a_missing_facet_reaches_a_manager_without_it(self, monkeypatch):
        res = await self._answer("facility_manager", self._partial(), monkeypatch)
        assert "doesn't record that" in res["response"] and "Owner" in res["response"]
        _assert_plain(res["response"])


# ── 1b. the capability agent passes the reader to the evidence read-back ───────


class TestProvenanceCaller:
    RECORD = {
        "status": "not_assessable",
        "operation": "observation",
        "remedy": "install a CO2 sensor and upload its TTL",
    }

    async def _answer(self, monkeypatch, role):
        import orchestrator.agents.capability_agent as cap
        import orchestrator.redis_manager as rm
        import orchestrator.services.building_context as bctx
        import orchestrator.services.capability_graph_resolver as cgr

        monkeypatch.setattr(bctx, "resolve_building_context", lambda _b: SimpleNamespace(name="B"))

        class _Resolver:
            async def resolve(self, _q):
                return []

        monkeypatch.setattr(cgr, "get_capability_graph_resolver", lambda: _Resolver())

        prev = SimpleNamespace(intermediate_results={"evidence_record": dict(self.RECORD)})

        async def _load_state(_cid):
            return prev

        monkeypatch.setattr(rm.redis_manager, "load_state", _load_state)
        state = await cap.CapabilityAgent().answer(_state("How do you know that?", role))
        return state.intermediate_results["capability_result"]

    async def test_a_manager_sees_the_record_without_the_remedy(self, monkeypatch):
        res = await self._answer(monkeypatch, "facility_manager")
        assert res["provenance"] == "answer_provenance"
        assert "How that answer was arrived at" in res["response"]
        assert "install a CO2 sensor" not in res["response"]
        _assert_plain(res["response"])

    async def test_an_admin_sees_the_remedy(self, monkeypatch):
        res = await self._answer(monkeypatch, "admin")
        assert "To make it answerable" in res["response"]
        assert "install a CO2 sensor" in res["response"]

    @pytest.mark.parametrize("role", (None, "guest", "superuser"))
    async def test_an_unknown_role_does_not_see_the_remedy(self, monkeypatch, role):
        res = await self._answer(monkeypatch, role)
        assert "install a CO2 sensor" not in res["response"]


# ── 2. the planner passes the reader to the spatial step ────────────────────────


class TestPlannerSpatialStep:
    async def _run(self, monkeypatch, role):
        import orchestrator.agents.spatial_agent as sp
        from orchestrator.agents.planner_agent import PlannerAgent, PlanStep

        seen = {}

        class _Spatial:
            async def resolve(self, query, building_id, floor=None, for_admin=False):
                seen["for_admin"] = for_admin
                return "no geometry"

        monkeypatch.setattr(sp, "get_spatial_agent", lambda: _Spatial())
        step = PlanStep(index=1, agent="spatial_query", description="area of floor 2")
        await PlannerAgent()._run_spatial_query(_state("area of floor 2", role), step)
        return seen["for_admin"]

    async def test_an_admin_reaches_the_spatial_agent_as_an_admin(self, monkeypatch):
        assert await self._run(monkeypatch, "admin") is True

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_every_other_reader_reaches_it_as_a_reader(self, monkeypatch, role):
        assert await self._run(monkeypatch, role) is False


# ── 3. the energy boundary line ─────────────────────────────────────────────────


class TestMeterBoundary:
    def _undeclared(self):
        from orchestrator.services.evidence.meter_boundary import MeterBoundary

        return [MeterBoundary(meter_iri="http://x#Energy_Meter_Floor2")]

    @pytest.mark.parametrize("which", ["none", "undeclared"])
    def test_a_reader_gets_the_verdict_and_no_instruction(self, which):
        from orchestrator.services.evidence.meter_boundary import statement

        boundaries = [] if which == "none" else self._undeclared()
        text = statement(boundaries, subject="Which floor used the most energy yesterday?")
        assert "Boundary: not declared" in text
        assert "can't" in text
        _assert_plain(text)

    @pytest.mark.parametrize("which", ["none", "undeclared"])
    def test_an_admin_is_told_what_to_state(self, which):
        from orchestrator.services.evidence.meter_boundary import statement

        boundaries = [] if which == "none" else self._undeclared()
        text = statement(boundaries, for_admin=True)
        assert "Boundary: not declared" in text
        assert "ontosage:meterServes" in text and "TTL" in text

    def test_the_question_is_not_pasted_into_the_sentence(self):
        """The caller passes question[:60] as ``subject``; interpolated, it read "whether it
        is the whole Which floor used the most energy yeste or one circuit within it"."""
        from orchestrator.services.evidence.meter_boundary import statement

        q = "Which floor used the most energy yesterday?"[:60]
        assert q not in statement(self._undeclared(), subject=q)

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    def test_an_unknown_role_gets_the_plain_line(self, role):
        from orchestrator.services.evidence.meter_boundary import statement

        _assert_plain(statement([], for_admin=_as_admin(role)))


# ── 4. describing itself ─────────────────────────────────────────────────────────


class TestSelfDescription:
    def _registry(self):
        return SimpleNamespace(intents=[SimpleNamespace(name="sensor_data")])

    FACTS = {
        "Sensors in the ontology": "2,720",
        "Instrumented points": "5,874",
        "Connected databases": "database1, database2",
    }
    SOURCES = ["Knowledge graph (SPARQL/GraphDB)", "Building ontology (triples)"]

    def test_a_reader_gets_the_identity_and_figures_in_plain_words(self):
        from orchestrator.services.self_description import describe

        out = describe(self._registry(), "B", facts=dict(self.FACTS), source_types=self.SOURCES)
        assert "OntoSage" in out and "2,720" in out and "5,874" in out
        assert "Connected data sources: **2**" in out
        assert "Knowledge graph" in out and "Building model" in out
        _assert_plain(out)

    def test_a_building_with_no_data_is_not_an_instruction_to_a_reader(self):
        from orchestrator.services.self_description import describe

        out = describe(self._registry(), "B", facts={})
        assert "No data loaded yet" in out
        _assert_plain(out)

    def test_an_admin_keeps_the_implementation_terms(self):
        from orchestrator.services.self_description import describe

        out = describe(
            self._registry(), "B", facts=dict(self.FACTS), source_types=self.SOURCES, for_admin=True
        )
        assert "TTL" in out and "database1" in out and "(triples)" in out
        empty = describe(self._registry(), "B", facts={}, for_admin=True)
        assert "register a database" in empty

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    def test_an_unknown_role_gets_the_plain_form(self, role):
        from orchestrator.services.self_description import describe

        _assert_plain(describe(self._registry(), "B", facts={}, for_admin=_as_admin(role)))


# ── 5. sensors on record with no readings ───────────────────────────────────────


class TestSqlNoReadings:
    async def test_the_decline_names_no_store_and_no_ontology(self, monkeypatch):
        import orchestrator.agents.sql_agent as sq

        class _Registry:
            is_available = True

            async def get_valid_uuids(self, uuids, primary, storage_map=None):
                return []

            def _resolve_storage_key(self, uri):
                return "database1"

        monkeypatch.setattr(sq, "adapter_registry", _Registry())
        agent = sq.SQLAgent.__new__(sq.SQLAgent)
        res = await agent.fetch_data_for_uuids(
            ["u1", "u2"], "temperature in room 1", storage_map={"u1": "bldg:database1"}
        )
        text = res["formatted_response"]
        assert "2 sensor(s)" in text
        assert "missing readings rather than missing sensors" in text
        _assert_plain(text)

    async def test_an_unreachable_store_names_no_ontology(self, monkeypatch):
        import orchestrator.agents.sql_agent as sq

        monkeypatch.setattr(sq, "adapter_registry", SimpleNamespace(is_available=False))
        agent = sq.SQLAgent.__new__(sq.SQLAgent)
        res = await agent.fetch_data_for_uuids(["u1"], "temperature")
        assert res["error"] == "database_unavailable"
        assert "unavailable" in res["formatted_response"]
        _assert_plain(res["formatted_response"])


# ── 6. a zero over a class the building never modelled ──────────────────────────


class TestUnmodelledEntities:
    @staticmethod
    async def _not_modelled(_q):
        return {"rows": [{"n": 0}]}

    async def test_a_reader_gets_the_distinction_from_none_and_no_remedy(self):
        from orchestrator.services.unmodelled_entities import guard_answer

        out, violation = await guard_answer("There are 0 desks available.", self._not_modelled)
        assert violation and "desks" in out
        assert "not the same as there being none" in out
        _assert_plain(out)

    async def test_an_admin_is_told_how_to_make_it_answerable(self):
        from orchestrator.services.unmodelled_entities import guard_answer

        out, _v = await guard_answer(
            "There are 0 desks available.", self._not_modelled, for_admin=True
        )
        assert "not the same as there being none" in out and "TTL" in out


# ── 7. inventory and metrics labels every reader sees ───────────────────────────


class TestLabels:
    def test_the_census_footer_is_plain(self):
        from orchestrator.services.ontology_inventory import render_census

        out = render_census([("Chiller", 3)], "B")
        assert "Chiller" in out and "3" in out and "building model" in out
        _assert_plain(out)

    def test_the_metrics_block_is_plain(self):
        from orchestrator.services.building_metrics import (
            BuildingMetricsSnapshot,
            render_metrics_block,
        )

        snap = BuildingMetricsSnapshot(
            total_points=5874,
            total_sensors=2720,
            reporting_sensors=2763,
            reporting_window_h=24,
            floor_count=8,
            floor_kinds=[("Floor", 6), ("Rooftop", 1), ("Parking_Level", 1)],
        )
        out = render_metrics_block(snap, "B")
        assert "5,874" in out and "2,720" in out and "2,763" in out
        assert "points" not in out.lower() and "brick" not in out.lower()
        _assert_plain(out)


# ── 8. an access denial ─────────────────────────────────────────────────────────


class TestAccessDenial:
    def _verdict(self):
        return SimpleNamespace(
            decision="deny",
            reason="no access policy is registered for role 'visitor'",
            alternative="",
            min_sensors=0,
            min_spaces=0,
            resolution_s=0,
            policy_iri="",
        )

    def test_the_reader_is_pointed_at_the_administrator_in_plain_words(self):
        from orchestrator.services.privacy.reformulation import render_refusal

        text = render_refusal(self._verdict(), "who is in room 1?")
        assert "I can't answer that" in text and "administrator" in text
        assert "policy" not in text.lower()
        _assert_plain(text)
