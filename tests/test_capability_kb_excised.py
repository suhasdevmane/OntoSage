# -*- coding: utf-8 -*-
"""TODO-081: the capability.yaml knowledge base is gone, and stays gone.

Capability facts are ``ontosage:Amenity`` / ``ontosage:KnowledgeTopic`` triples
served by CapabilityGraphResolver (TODO-012). The Qdrant KB that preceded them —
the indexer, the schema models, and SemanticRouter.classify() with its search
and cache machinery — had no caller left. This file pins the removal and, more
importantly, pins what had to SURVIVE it: routing still works without Qdrant,
an embedding model, or any per-building state.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


class TestTheDeadModulesAreGone:
    @pytest.mark.parametrize(
        "module",
        ["shared.capability_schema", "orchestrator.services.capability_indexer"],
    )
    def test_module_no_longer_exists(self, module):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)

    @pytest.mark.parametrize(
        "attr",
        [
            "classify",
            "register_intent",
            "search_capability_entries",
            "_get_kb",
            "_search_capability",
            "_get_routing_config",
            "_documents_route_signal",
        ],
    )
    def test_the_kb_machinery_is_gone(self, attr):
        assert not hasattr(SemanticRouter, attr), f"{attr} came back"


class TestRoutingSurvivedWithoutIt:
    """The load-bearing half: pure predicates, callable on the CLASS."""

    def test_the_guards_need_no_instance_and_no_clients(self):
        """No Qdrant, no embedder, no building state — routing must not need them."""
        assert SemanticRouter.is_data_query("what is the temperature in RM101?") is True
        assert SemanticRouter.is_control_command("open the windows") is True
        assert SemanticRouter.is_report_intake_query("the toilet is leaking") is True
        assert SemanticRouter.is_floor_plan_query("show me floor 2") is True

    def test_a_report_still_classifies_to_its_kind(self):
        assert SemanticRouter.report_intake_intent("the toilet is leaking") == "maintenance"

    def test_the_guards_are_pure(self):
        """Same input, same verdict — no cache, no order dependence.

        CAVEAT-171 existed because the deleted classify() tests depended on
        embedding state some sibling test file happened to initialise, so they
        failed when run alone. Nothing here can develop that problem.
        """
        q = "what is the CO2 in RM101?"
        assert SemanticRouter.is_data_query(q) == SemanticRouter.is_data_query(q)

    def test_routing_contract_still_binds_the_router(self):
        """routing_contract imports SemanticRouter as `sr` for its rule context."""
        rc = importlib.import_module("orchestrator.services.routing_contract")
        src = Path(rc.__file__).read_text(encoding="utf-8")
        assert "SemanticRouter" in src, "the contract lost its guard binding"


class TestTheReindexTargetIsHonest:
    @pytest.mark.asyncio
    async def test_capability_target_says_why_it_does_nothing(self):
        """An old client asking to re-index capabilities gets a reason, not silence."""
        from orchestrator.services.reindex_service import ReindexService

        result = await ReindexService()._run_target("capability", "bldg1")
        assert "skipped" in result
        assert "triples" in result["skipped"].lower()
