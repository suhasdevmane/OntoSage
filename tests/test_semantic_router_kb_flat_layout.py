"""Regression test: SemanticRouter loads the capability KB from the FLAT layout.

Root cause of the capability-grounding failure: the router's _get_kb only read
input/<id>/capability.yaml (nested). In the active flat layout
(input/capability.yaml) it returned None, so every capability match resolved to
entry=None and was filtered out — capability answers never grounded even on a
0.9+ semantic hit. (Same flat-vs-nested class as the agent loader / BuildingRegistry.)

_get_kb only touches _input_root, so the router can be built with None clients.
"""

import shutil
from pathlib import Path

import pytest

from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit

_REAL = Path(__file__).resolve().parents[1] / "input" / "capability.yaml"
_skip = pytest.mark.skipif(not _REAL.exists(), reason="input/capability.yaml not present")


@_skip
def test_router_get_kb_flat_layout(tmp_path):
    shutil.copy(_REAL, tmp_path / "capability.yaml")  # FLAT: input/capability.yaml
    router = SemanticRouter(qdrant_client=None, embedding_service=None, input_root=str(tmp_path))
    kb = router._get_kb("bldg1")
    assert kb is not None, "router must find flat-layout capability.yaml"
    assert len(kb.capabilities) > 0


@_skip
def test_router_get_kb_nested_layout(tmp_path):
    (tmp_path / "bldg1").mkdir()
    shutil.copy(_REAL, tmp_path / "bldg1" / "capability.yaml")
    router = SemanticRouter(qdrant_client=None, embedding_service=None, input_root=str(tmp_path))
    assert router._get_kb("bldg1") is not None


def test_router_get_kb_missing_returns_none(tmp_path):
    router = SemanticRouter(qdrant_client=None, embedding_service=None, input_root=str(tmp_path))
    assert router._get_kb("bldg1") is None
