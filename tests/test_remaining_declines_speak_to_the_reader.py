# -*- coding: utf-8 -*-
"""The remaining declines speak to the person reading them (2026-09-17, user decision).

``test_declines_speak_to_the_reader.py`` pinned the decision on the sensor, observability and
capability lanes. These are the lanes it did not reach, each of which still told EVERY reader
to change the building's data:

* "how old is this building?"  -> "On the building's own node in its TTL assert brick:yearBuilt"
* an empty compliance register -> "Upload the register as ComplianceCheck triples"
* no events store              -> "Register an `events_data` source"
* no lift / schedule records   -> "Describe them in the ontology" / "Add them as
                                   ontosage:ServiceSchedule entries"
* a what-if with no history    -> "Add occupancy sensing"
* evidence gates and omissions -> "Install or connect a sensor", "restart the publisher"
* floor plans                  -> "Make sure the DWG files have been ingested"

The decision, as for the first set: every reader keeps the HONEST DECLINE (design contract 4)
and what IS available; only a reader whose authenticated role holds ``system:admin`` also sees
how to fix it; an unknown or missing role is not an administrator.

Each site is asked: does a non-admin see the verdict, does a non-admin see none of the
remediation jargon, does an admin see the remediation, and does an unknown role get the plain
form.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit

#: Words that only make sense to someone editing the building's data.
JARGON = (
    "TTL",
    "triples",
    "upload",
    "ingest",
    "front-matter",
    "ontology",
    "admin portal",
    "admin console",
    "ref:",
    "brick:",
    "yearBuilt",
    "ComplianceCheck",
    "ServiceSchedule",
    "events_data",
    "DWG",
    "/app/input",
    "no code change",
    "install",
    "occupancy sensing",
    "publisher",
    "archival interval",
    "calibration date",
    "register an",
    "onboarding contract",
)

UNKNOWN_ROLES = (None, "", "guest", "superuser", "facility_manager", 7)


def _assert_plain(text: str) -> None:
    lowered = text.lower()
    for word in JARGON:
        assert word.lower() not in lowered, f"{word!r} reached a non-admin reader:\n{text}"


def _as_admin(role) -> bool:
    from orchestrator.services.grounding_guard import reader_is_admin

    return reader_is_admin(role)


# ── the building describing itself ───────────────────────────────────────────


class TestBuildingProfile:
    def test_a_building_stating_nothing_declines_plainly(self):
        from orchestrator.services import building_profile as bp

        text = bp.enablement_hint("Test Building")
        assert "Test Building" in text and "doesn't record" in text and "won't guess" in text
        _assert_plain(text)

    def test_an_admin_is_told_what_to_assert(self):
        from orchestrator.services import building_profile as bp

        text = bp.enablement_hint("Test Building", for_admin=True)
        assert "doesn't record" in text
        assert "yearBuilt" in text and "TTL" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    def test_an_unknown_role_gets_the_plain_decline(self, role):
        from orchestrator.services import building_profile as bp

        _assert_plain(bp.enablement_hint("T", for_admin=_as_admin(role)))

    def _partial(self):
        from orchestrator.services import building_profile as bp

        return bp.BuildingProfile(facts={"Owner": "Acme"}, facets={"owner": "Acme"}, resolved=True)

    def test_a_missing_facet_names_what_is_recorded_to_everyone(self):
        from orchestrator.services import building_profile as bp

        text = bp.render(self._partial(), "age", "T")
        assert "doesn't record that" in text and "Owner" in text
        _assert_plain(text)

    def test_a_missing_facet_tells_an_admin_how_to_add_it(self):
        from orchestrator.services import building_profile as bp

        text = bp.render(self._partial(), "age", "T", for_admin=True)
        assert "Owner" in text and "TTL" in text and "no code change" in text

    def test_an_unresolved_lookup_names_no_internals(self):
        from orchestrator.services import building_profile as bp

        text = bp.render(bp.BuildingProfile(), "age", "T")
        assert "couldn't look up" in text
        _assert_plain(text)


# ── registers, events and asset state ───────────────────────────────────────


class _EmptyRegister:
    async def __call__(self, query: str) -> dict:
        if "COUNT(" in query:
            return {"results": {"bindings": [{"n": {"value": "0"}}]}}
        return {"results": {"bindings": []}}


class TestComplianceRegister:
    async def _answer(self, **kw):
        from orchestrator.services.compliance_register_service import (
            ComplianceRegisterService,
        )

        svc = ComplianceRegisterService(_EmptyRegister(), "http://example.org/b#")
        return (await svc.answer("Which checks are overdue?", **kw))["formatted_response"]

    async def test_a_non_admin_is_told_no_register_is_held(self):
        text = await self._answer()
        assert "No compliance register is held" in text
        _assert_plain(text)

    async def test_an_admin_is_told_how_to_load_one(self):
        text = await self._answer(for_admin=True)
        assert "No compliance register is held" in text
        assert "ComplianceCheck triples" in text and "admin portal" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_decline(self, role):
        _assert_plain(await self._answer(for_admin=_as_admin(role)))


class TestEvents:
    async def _answer(self, **kw):
        from orchestrator.services.event_query_service import EventQueryService

        svc = EventQueryService("anybuilding", None, [])
        return (await svc.answer("Which rooms are free today?", **kw))["formatted_response"]

    async def test_a_non_admin_is_told_what_is_not_kept_and_what_still_can_be_asked(self):
        text = await self._answer()
        assert "doesn't keep records of bookings" in text
        assert "faults people have reported" in text
        _assert_plain(text)

    async def test_an_admin_is_told_which_source_to_register(self):
        text = await self._answer(for_admin=True)
        assert "doesn't keep records of bookings" in text
        assert "events_data" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_decline(self, role):
        _assert_plain(await self._answer(for_admin=_as_admin(role)))


async def _no_rows(query: str) -> dict:
    return {"results": {"bindings": []}}


class TestAssetState:
    @pytest.mark.parametrize(
        "question,verdict,remedy",
        [
            ("Are the lifts working?", "no lifts on record", "Describe them in the ontology"),
            (
                "When is the cleaning schedule?",
                "no cleaning or service schedules on record",
                "ontosage:ServiceSchedule",
            ),
        ],
    )
    async def test_declines_by_reader(self, question, verdict, remedy):
        from orchestrator.services.asset_state_service import AssetStateService

        svc = AssetStateService(_no_rows, "http://example.org/b#")
        plain = (await svc.answer(question))["formatted_response"]
        assert verdict in plain
        _assert_plain(plain)
        admin = (await svc.answer(question, for_admin=True))["formatted_response"]
        assert verdict in admin and remedy in admin
        for role in UNKNOWN_ROLES:
            text = (await svc.answer(question, for_admin=_as_admin(role)))["formatted_response"]
            _assert_plain(text)


# ── what-if scenarios ────────────────────────────────────────────────────────


class TestScenarioDecline:
    def test_a_non_admin_is_offered_a_space_with_history_not_told_to_add_sensing(self):
        from orchestrator.services.deliberation.scenarios import decline_reason

        text = decline_reason("co2", None)
        assert "no paired" in text and "record occupancy" in text
        _assert_plain(text)

    def test_an_admin_is_told_to_add_sensing(self):
        from orchestrator.services.deliberation.scenarios import decline_reason

        text = decline_reason("co2", None, for_admin=True)
        assert "no paired" in text and "occupancy sensing" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    def test_an_unknown_role_gets_the_plain_decline(self, role):
        from orchestrator.services.deliberation.scenarios import decline_reason

        _assert_plain(decline_reason("co2", None, for_admin=_as_admin(role)))


# ── evidence gates, not-assessable narration, omissions, provenance ─────────


def _policy():
    from orchestrator.services.evidence import load_policy

    return load_policy("any")


def _failing_verdicts():
    from datetime import datetime, timedelta, timezone

    from orchestrator.services.evidence import gates
    from shared.models import SpatialAdequacy

    policy = _policy()
    now = datetime(2026, 9, 17, 12, 0, tzinfo=timezone.utc)
    return {
        "no_observation": gates.freshness_gate(policy, "co2", None, now),
        "stale": gates.freshness_gate(policy, "co2", now - timedelta(days=3), now),
        "no_cadence": gates.completeness_gate(policy, None),
        "low_coverage": gates.completeness_gate(policy, 0.01),
        "no_sensor": gates.spatial_gate(policy, SpatialAdequacy.NONE, "space"),
        "uncalibrated": gates.calibration_gate(policy, "expired", "safety_or_compliance"),
    }


class TestEvidenceGates:
    @pytest.mark.parametrize("name", sorted(_failing_verdicts()))
    def test_a_non_admin_sees_the_reason_and_no_remedy(self, name):
        verdict = _failing_verdicts()[name]
        assert not verdict.passed
        text = verdict.describe()
        assert verdict.reason and text.startswith(verdict.reason)
        _assert_plain(text)

    @pytest.mark.parametrize("name", sorted(_failing_verdicts()))
    def test_an_admin_sees_the_remedy(self, name):
        verdict = _failing_verdicts()[name]
        assert not verdict.passed
        assert verdict.remedy and verdict.remedy in verdict.describe(for_admin=True)

    def test_the_sensor_install_remedy_is_kept_for_the_admin_and_the_record(self):
        verdict = _failing_verdicts()["no_sensor"]
        assert "connect a sensor" in verdict.remedy.lower()
        assert "sensor" not in verdict.describe().lower().replace(verdict.reason.lower(), "")

    def test_a_reader_safe_next_step_still_reaches_everyone(self):
        stale = _failing_verdicts()["stale"]
        assert not stale.passed
        assert "past observation" in stale.describe()

    def test_not_assessable_narration_withholds_the_remedy_by_default(self):
        from orchestrator.services.evidence.narration import describe_not_assessable

        plain = describe_not_assessable("no sensor covers the space asked about", "Install one.")
        assert "Not assessable" in plain and "No sensor covers" in plain
        assert "Install one" not in plain and "What would make this answerable" not in plain
        admin = describe_not_assessable(
            "no sensor covers the space asked about", "Install one.", for_admin=True
        )
        assert "What would make this answerable:** Install one." in admin
        stepped = describe_not_assessable("too little observed", "Restore data.", next_step="Ask.")
        assert stepped.endswith("Ask.") and "Restore data" not in stepped

    def test_omissions_carry_a_plain_note_for_readers_and_the_remedy_for_admins(self):
        from orchestrator.services.evidence.omissions import (
            CriterionFacts,
            collect,
            render,
        )

        facts = [
            CriterionFacts("quietest", "noise", instrumented=False),
            CriterionFacts("warmest", "temperature", has_readings=False),
            CriterionFacts("brightest", "illuminance", is_stale=True),
            CriterionFacts("nearest", "co2", proxy_only=True),
        ]
        plain = render(collect(facts))
        assert "quietest" in plain and "warmest" in plain
        for word in ("Instrumenting", "registering the readings", "Connecting readings"):
            assert word not in plain
        admin = render(collect(facts, for_admin=True))
        assert "Instrumenting it" in admin and "Connecting readings" in admin

    def test_the_provenance_read_back_withholds_the_remedy_by_default(self):
        from orchestrator.services.answer_provenance import render

        record = {
            "status": "not_assessable",
            "not_assessable_reason": "no sensor covers the space asked about",
            "remedy": "Install or connect a sensor in this space to answer it directly.",
        }
        plain = render(record, "how do you know that?")
        assert "not_assessable" in plain
        _assert_plain(plain)
        admin = render(record, "how do you know that?", for_admin=True)
        assert "To make it answerable:** Install or connect a sensor" in admin


# ── floor plans ──────────────────────────────────────────────────────────────


class TestSpatialDeclines:
    async def _resolve(self, monkeypatch, manifests, **kw):
        from orchestrator.agents.spatial_agent import SpatialAgent

        agent = SpatialAgent()
        monkeypatch.setattr(agent, "_load_manifests", lambda building_id, floor: manifests)
        return await agent.resolve("how big is room 1?", "anybuilding", **kw)

    async def test_no_floor_plans_declines_plainly(self, monkeypatch):
        text = await self._resolve(monkeypatch, [])
        assert "No floor plan data is available" in text
        _assert_plain(text)
        admin = await self._resolve(monkeypatch, [], for_admin=True)
        assert "DWG files have been ingested" in admin

    async def test_plans_without_geometry_say_what_they_do_hold(self, monkeypatch):
        spaces = [SimpleNamespace(area_m2=None), SimpleNamespace(area_m2=None)]
        manifests = [SimpleNamespace(spaces=spaces, floor=0)]
        text = await self._resolve(monkeypatch, manifests)
        assert "name 2 space(s) across 1 floor(s)" in text
        assert "areas and shapes are not available" in text
        _assert_plain(text)
        admin = await self._resolve(monkeypatch, manifests, for_admin=True)
        assert "DWG source files" in admin

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_decline(self, monkeypatch, role):
        _assert_plain(await self._resolve(monkeypatch, [], for_admin=_as_admin(role)))


# ── callers that must pass the role through ─────────────────────────────────

NS = "http://example.org/anybuilding#"


def _graph(uris):
    """Stub SPARQL exec matching every term against a known URI's local name."""

    async def _exec(q: str) -> dict:
        import re as _re

        terms = [t.lower() for t in _re.findall(r'CONTAINS\(\?local, "([^"]+)"\)', q)]
        if not terms:
            return {"results": {"bindings": []}}
        combine = all if "SELECT ?s WHERE" in q else any
        hits = [u for u in uris if combine(t in u.rsplit("#", 1)[-1].lower() for t in terms)]
        return {"results": {"bindings": [{"s": {"value": u}} for u in hits]}}

    return _exec


class TestReferentResolverPassesTheRoleThrough:
    async def _resolve(self, **kw):
        import orchestrator.services.referent_resolver as rr

        resolver = rr.ReferentResolver(_graph([NS + "Floor2", NS + "Floor3"]))
        res = await resolver.resolve("How many sensors are on floor 42?", [], NS, "Any", **kw)
        assert res.status == rr.NOT_FOUND
        return res.message

    async def test_a_non_admin_keeps_the_decline_and_what_exists(self):
        text = await self._resolve()
        assert "floor 42" in text and ("Floor2" in text or "Floor3" in text)
        _assert_plain(text)

    async def test_an_admin_is_given_the_remediation(self):
        text = await self._resolve(for_admin=True)
        assert "floor 42" in text and "Describe it in the ontology" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_decline(self, role):
        _assert_plain(await self._resolve(for_admin=_as_admin(role)))


class TestReportAgentPassesTheRoleThrough:
    async def _generate(self, monkeypatch, role):
        from orchestrator.agents.report_agent import ReportAgent

        agent = ReportAgent()

        async def _sections(*_a, **_k):
            return {"overview": {"data_points": 0, "sensor_count": 0}}

        monkeypatch.setattr(agent, "_build_sections", _sections)
        # Only the narrative matters here; the report scaffolding needs a full sections dict.
        monkeypatch.setattr(
            agent,
            "_assemble_report",
            lambda _rtype, _sections, narrative: {"formatted_text": narrative},
        )
        results = {} if role is None else {"user_role": role}
        state = SimpleNamespace(intermediate_results=results, building_id=None, persona="general")
        text = (await agent.generate(state, "report on the radiation in the atrium"))[
            "formatted_text"
        ]
        # Never let a failed generate pass a "remediation absent" assertion vacuously.
        assert "No data was retrieved" in text
        return text

    async def test_a_non_admin_report_declines_without_remediation(self, monkeypatch):
        text = await self._generate(monkeypatch, "facility_manager")
        assert "Add the sensor to the ontology" not in text
        _assert_plain(text)

    async def test_an_admin_report_carries_the_remediation(self, monkeypatch):
        text = await self._generate(monkeypatch, "admin")
        assert "Add the sensor to the ontology" in text

    @pytest.mark.parametrize("role", UNKNOWN_ROLES)
    async def test_an_unknown_role_gets_the_plain_report(self, monkeypatch, role):
        _assert_plain(await self._generate(monkeypatch, role))
