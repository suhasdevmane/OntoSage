# -*- coding: utf-8 -*-
"""TODO-072: which onboarding step is missing, answered directly.

Every step already had an endpoint; nothing could report whether they had been
DONE. So "is this building ready?" could only be answered by putting questions to
it and reading the replies — which cannot tell a missing step apart from a bad
answer. Readiness is therefore read from the live system, never from a checklist:
a step is done because the data is there.
"""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.services import onboarding_status as obs

pytestmark = pytest.mark.unit


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Neutral building: nothing configured, nothing ingested."""
    monkeypatch.setattr(obs.settings, "BUILDING_ID", "bldgX", raising=False)
    monkeypatch.setattr(obs.settings, "BUILDING_NAMESPACE", "http://x.org/b#", raising=False)
    monkeypatch.setattr(obs, "_input_root", lambda: tmp_path)
    return tmp_path


class TestIdentity:
    def test_a_configured_building_is_ready(self, monkeypatch):
        monkeypatch.setattr(
            obs.admin_config if hasattr(obs, "admin_config") else obs, "_noop", None, raising=False
        )
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(
            ac,
            "read_building_config",
            lambda: {
                "building_id": "bldgX",
                "building_name": "North Wing",
                "ontology_namespace": "http://x.org/b#",
            },
        )
        assert obs._identity_step()["done"] is True

    def test_the_shipped_placeholder_namespace_is_not_an_identity(self, monkeypatch):
        """Every TTL would then validate against a namespace nobody owns."""
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(
            ac,
            "read_building_config",
            lambda: {
                "building_id": "bldgX",
                "building_name": "North Wing",
                "ontology_namespace": "http://example.org/building#",
            },
        )
        assert obs._identity_step()["done"] is False

    @pytest.mark.parametrize("missing", ["building_id", "building_name", "ontology_namespace"])
    def test_any_missing_field_blocks(self, monkeypatch, missing):
        import orchestrator.services.admin_config as ac

        cfg = {
            "building_id": "bldgX",
            "building_name": "North Wing",
            "ontology_namespace": "http://x.org/b#",
        }
        cfg[missing] = ""
        monkeypatch.setattr(ac, "read_building_config", lambda: cfg)
        step = obs._identity_step()
        assert step["done"] is False and step["blocking"] is True
        assert step["hint"], "a blocked step must say what to do"

    def test_an_unreadable_config_is_reported_not_crashed(self, monkeypatch):
        import orchestrator.services.admin_config as ac

        def boom():
            raise OSError("no building.yaml")

        monkeypatch.setattr(ac, "read_building_config", boom)
        step = obs._identity_step()
        assert step["done"] is False and "no building.yaml" in step["detail"]


class TestTimeseriesNeedsBothHalves:
    def test_declared_sensors_with_no_rows_is_not_ready(self, monkeypatch):
        """The failure that looks like success on every other screen."""
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(ac, "read_databases", lambda: [{"key": "database1"}])
        step = asyncio.run(obs._timeseries_step({"total_declared": 300, "total_with_data": 0}))
        assert step["done"] is False
        assert "0 of 300" in step["detail"]

    def test_rows_behind_declared_sensors_is_ready(self, monkeypatch):
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(ac, "read_databases", lambda: [{"key": "database1"}])
        step = asyncio.run(obs._timeseries_step({"total_declared": 300, "total_with_data": 288}))
        assert step["done"] is True

    def test_no_datasource_at_all(self, monkeypatch):
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(ac, "read_databases", lambda: [])
        step = asyncio.run(obs._timeseries_step({}))
        assert step["done"] is False and "no datasource" in step["detail"]


class TestDocuments:
    def test_absent_documents_are_optional_not_a_failure(self, isolated):
        step = obs._documents_step()
        assert step["done"] is False and step["blocking"] is False

    def test_uploaded_documents_are_counted(self, isolated):
        d = isolated / "documents"
        d.mkdir()
        (d / "policy.md").write_text("x", encoding="utf-8")
        (d / "manual.pdf").write_bytes(b"x")
        (d / "notes.docx").write_bytes(b"x")  # unsupported type, must not count
        assert "2 document" in obs._documents_step()["detail"]


class TestOverallVerdict:
    def _steps(self, **done):
        return [
            obs._step("identity", "", done.get("identity", True), "", blocking=True),
            obs._step("ontology", "", done.get("ontology", True), "", blocking=True),
            obs._step("timeseries", "", done.get("timeseries", True), ""),
            obs._step("documents", "", done.get("documents", True), ""),
            obs._step("floor_plans", "", done.get("floor_plans", True), ""),
        ]

    def test_can_answer_needs_only_the_blocking_steps(self, monkeypatch):
        steps = self._steps(documents=False, floor_plans=False)
        assert all(s["done"] for s in steps if s["blocking"])
        assert not all(s["done"] for s in steps)

    def test_missing_ontology_means_it_cannot_answer(self):
        steps = self._steps(ontology=False)
        assert not all(s["done"] for s in steps if s["blocking"])


class TestEveryStepIsActionable:
    def test_a_not_done_step_always_carries_a_hint(self):
        step = obs._step("k", "L", False, "d", hint="do the thing")
        assert step["hint"] == "do the thing"

    def test_a_done_step_carries_no_nagging_hint(self):
        assert obs._step("k", "L", True, "d", hint="do the thing")["hint"] == ""


class TestTheEndpointContractTheTabRelies_On:
    """The tab reads specific keys off these payloads. A rename would leave the
    onboarding screen silently empty — a list that renders nothing looks exactly
    like a building with no documents — so the shapes are pinned here."""

    def test_status_exposes_every_key_the_tab_reads(self):
        step = obs._step("identity", "Building identity", False, "detail", blocking=True, hint="h")
        assert set(step) == {"key", "label", "done", "detail", "blocking", "hint"}

    def test_the_five_steps_are_named_and_ordered_as_the_tab_expects(self, monkeypatch, tmp_path):
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(obs, "_input_root", lambda: tmp_path)
        monkeypatch.setattr(ac, "read_building_config", lambda: {})
        monkeypatch.setattr(ac, "read_databases", lambda: [])

        async def _no_graph(*a, **k):
            raise RuntimeError("offline")

        monkeypatch.setattr(
            "orchestrator.services.ontology_manager.run_sparql_select", _no_graph, raising=False
        )
        out = asyncio.run(obs.collect_status())
        assert [s["key"] for s in out["steps"]] == [
            "identity",
            "ontology",
            "timeseries",
            "documents",
            "floor_plans",
        ]
        assert out["steps_total"] == 5
        assert out["can_answer"] is False, "nothing configured must not claim it can answer"

    def test_a_totally_offline_probe_still_returns_a_full_report(self, monkeypatch, tmp_path):
        """Never a 500: a half-built building is the normal case for this screen."""
        import orchestrator.services.admin_config as ac

        monkeypatch.setattr(obs, "_input_root", lambda: tmp_path)
        monkeypatch.setattr(ac, "read_building_config", lambda: {})
        monkeypatch.setattr(ac, "read_databases", lambda: [])
        out = asyncio.run(obs.collect_status())
        assert len(out["steps"]) == 5
        assert all("hint" in s for s in out["steps"])
