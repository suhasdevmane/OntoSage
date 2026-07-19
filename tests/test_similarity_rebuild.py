"""
Unit tests for ontology_manager similarity-index management.

- rebuild = DELETE + CREATE (GraphDB 10.7.4's in-place SPARQL rebuildIndex trigger hangs; a
  delete+create rebuilds the Lucene text index cleanly in seconds).
- ensure = create-if-missing via ``POST /rest/similarity`` (the correct GraphDB 10.x path;
  ``/rest/similarity/indexes`` 405s), so the index self-heals on a fresh volume.

No live GraphDB — helpers are monkeypatched / fake httpx clients record the requests.
"""

from __future__ import annotations

import pytest

from orchestrator.services import ontology_manager as om
from shared.config import settings

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, code, text="", payload=None):
        self.status_code = code
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload


# ── rebuild = delete + create ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rebuild_recreates(monkeypatch):
    """rebuild deletes then recreates the index (in that order) and reports 'rebuilding'."""
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", True)
    calls = []

    async def _del(index, base, auth, client):
        calls.append("delete")
        return True

    async def _cre(index, base, auth, client):
        calls.append("create")
        return {"ok": True, "created": True, "error": None}

    monkeypatch.setattr(om, "_delete_similarity_index", _del)
    monkeypatch.setattr(om, "_create_similarity_index", _cre)

    res = await om.rebuild_similarity_index(client=object())
    assert res["ok"] is True and res["status"] == "rebuilding"
    assert calls == ["delete", "create"]  # delete BEFORE create


@pytest.mark.asyncio
async def test_rebuild_reports_create_failure(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", True)

    async def _del(index, base, auth, client):
        return True

    async def _cre(index, base, auth, client):
        return {"ok": False, "created": False, "error": "HTTP 500: boom"}

    monkeypatch.setattr(om, "_delete_similarity_index", _del)
    monkeypatch.setattr(om, "_create_similarity_index", _cre)

    res = await om.rebuild_similarity_index(client=object())
    assert res["ok"] is False and "boom" in res["error"]


@pytest.mark.asyncio
async def test_rebuild_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", False)
    called = {"n": 0}

    async def _cre(*a, **k):
        called["n"] += 1
        return {"ok": True, "created": True, "error": None}

    monkeypatch.setattr(om, "_create_similarity_index", _cre)
    res = await om.rebuild_similarity_index(client=object())
    assert res["ok"] is True and res["status"] == "disabled"
    assert called["n"] == 0  # nothing created when similarity is disabled


# ── ensure = create-if-missing (real function, fake GET+POST client) ─────────


class _RestClient:
    def __init__(self, existing, create_code=200):
        self._existing = existing  # list of {"name": ...}
        self._create_code = create_code
        self.posted = None

    async def get(self, url, headers=None, auth=None):
        return _Resp(200, payload=self._existing)

    async def post(self, url, json=None, headers=None, auth=None):
        self.posted = {"url": url, "json": json}
        return _Resp(self._create_code)


@pytest.mark.asyncio
async def test_ensure_noop_when_present(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", True)
    c = _RestClient([{"name": settings.GRAPHDB_SIMILARITY_INDEX}])
    res = await om.ensure_similarity_index(client=c)
    assert res["ok"] and res["exists"] and not res["created"]
    assert c.posted is None  # already present → no create


@pytest.mark.asyncio
async def test_ensure_creates_when_missing(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", True)
    c = _RestClient([])  # empty listing → must create
    res = await om.ensure_similarity_index(client=c)
    assert res["ok"] and res["created"] and not res["exists"]
    assert c.posted["url"].endswith("/rest/similarity")  # correct GraphDB 10.x path
    assert c.posted["json"]["name"] == settings.GRAPHDB_SIMILARITY_INDEX
    assert c.posted["json"]["type"] == "text"


@pytest.mark.asyncio
async def test_ensure_disabled_is_noop(monkeypatch):
    monkeypatch.setattr(settings, "GRAPHDB_USE_SIMILARITY", False)
    c = _RestClient([])
    res = await om.ensure_similarity_index(client=c)
    assert res["ok"] and not res["created"]
    assert c.posted is None
