"""Phase 10E — SPARQL agent prefix block per building.

Verifies that `_prefix_block(building_id=...)` reads namespace and prefix
from BuildingContext rather than process-global settings.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from orchestrator.services import building_context as bc_mod
from orchestrator.services.building_context import BuildingContext


def _stub_ctx(name="Alpha", namespace="http://alpha.example#", prefix="alpha", tz="UTC"):
    return BuildingContext(
        building_id="testid",
        name=name,
        namespace=namespace,
        prefix=prefix,
        timezone=tz,
    )


def test_prefix_block_uses_per_building_namespace_when_building_id_given():
    """_prefix_block(building_id='alpha') uses that building's namespace."""
    from orchestrator.agents.sparql_agent import SPARQLAgent

    agent = SPARQLAgent.__new__(SPARQLAgent)
    with patch.object(
        bc_mod,
        "resolve_building_context",
        return_value=_stub_ctx(
            namespace="http://alpha.example/zones#",
            prefix="alpha",
        ),
    ):
        block = agent._prefix_block(building_id="alpha")

    assert "alpha" in block
    assert "alpha.example" in block
    # Standard prefixes still present
    assert "brick" in block.lower() or "PREFIX brick" in block


def test_prefix_block_falls_back_to_global_when_no_building_id():
    """_prefix_block() with no arg uses the process-global EXTENDED_PREFIXES."""
    from orchestrator.agents.sparql_agent import EXTENDED_PREFIXES, SPARQLAgent

    agent = SPARQLAgent.__new__(SPARQLAgent)
    block = agent._prefix_block()
    # Must match the EXTENDED_PREFIXES constant byte-for-byte
    assert block == "\n".join(EXTENDED_PREFIXES)


def test_prefix_block_handles_resolver_failure_gracefully():
    """When the resolver raises, _prefix_block falls back to EXTENDED_PREFIXES."""
    from orchestrator.agents.sparql_agent import EXTENDED_PREFIXES, SPARQLAgent

    agent = SPARQLAgent.__new__(SPARQLAgent)
    with patch.object(
        bc_mod,
        "resolve_building_context",
        side_effect=RuntimeError("boom"),
    ):
        block = agent._prefix_block(building_id="anything")
    assert block == "\n".join(EXTENDED_PREFIXES)


def test_two_buildings_produce_different_prefix_blocks():
    """Different building_ids → different namespaces in the prefix block."""
    from orchestrator.agents.sparql_agent import SPARQLAgent

    agent = SPARQLAgent.__new__(SPARQLAgent)
    with patch.object(
        bc_mod,
        "resolve_building_context",
        return_value=_stub_ctx(namespace="http://north.example#", prefix="north"),
    ):
        a = agent._prefix_block(building_id="north")
    with patch.object(
        bc_mod,
        "resolve_building_context",
        return_value=_stub_ctx(namespace="http://south.example#", prefix="south"),
    ):
        b = agent._prefix_block(building_id="south")
    assert "north.example" in a
    assert "south.example" in b
    assert "north.example" not in b
    assert "south.example" not in a
