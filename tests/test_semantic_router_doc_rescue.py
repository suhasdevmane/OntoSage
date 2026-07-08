"""Unit tests for the documents-KB routing rescue.

Policy / governance / privacy questions live in documents_<bldg>, not
capability.yaml. The router probes the documents collection and, when a building
document matches above the threshold, routes the query to the capability node so
its doc-search fallback grounds the answer. _documents_route_signal returns the
top documents similarity score (0.0 on miss / outage). Offline — fake Qdrant.
"""

import pytest

import orchestrator.services.semantic_router as sr
from orchestrator.services.semantic_router import SemanticRouter

pytestmark = pytest.mark.unit


class _Pt:
    def __init__(self, score):
        self.score = score


class _Res:
    def __init__(self, points):
        self.points = points


class _FakeQdrant:
    def __init__(self, score=None, raises=False):
        self._score = score
        self._raises = raises

    async def query_points(self, **kwargs):
        if self._raises:
            raise RuntimeError("qdrant down")
        return _Res([_Pt(self._score)] if self._score is not None else [])


def _router(qdrant):
    return SemanticRouter(qdrant_client=qdrant, embedding_service=None, input_root="/tmp")


@pytest.mark.asyncio
async def test_documents_signal_returns_top_score():
    r = _router(_FakeQdrant(score=0.61))
    assert await r._documents_route_signal([0.1] * 8, "bldg1") == pytest.approx(0.61)


@pytest.mark.asyncio
async def test_documents_signal_empty_returns_zero():
    r = _router(_FakeQdrant(score=None))
    assert await r._documents_route_signal([0.1] * 8, "bldg1") == 0.0


@pytest.mark.asyncio
async def test_documents_signal_error_returns_zero():
    r = _router(_FakeQdrant(raises=True))
    assert await r._documents_route_signal([0.1] * 8, "bldg1") == 0.0


def test_doc_kb_routing_defaults():
    # Enabled by default; threshold calibrated to separate governance (~0.4-0.6)
    # from generic queries (~0.03).
    assert sr._DOC_KB_ROUTING_ENABLED is True
    assert sr._DOC_KB_ROUTE_THRESHOLD == pytest.approx(0.38)
