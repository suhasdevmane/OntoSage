# -*- coding: utf-8 -*-
"""BUG-203: a TTL correction cannot reach the default graph, so say so.

Every TTL is published with PUT ?context=<named graph>, which REPLACES that
graph and by construction touches nothing outside it. A triple that reached the
default graph by any other route is therefore immune to every later correction:
the file gets fixed, the upload reports success, and the graph keeps answering
from the old copy. TODO-181 hit this — 52 subjects ended up carrying BOTH the
old and the new type — and BUG-194 was a policy edit shadowed the same way.
"""

from __future__ import annotations

import json

import pytest

from orchestrator.services import ttl_uploader

pytestmark = pytest.mark.unit


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        if isinstance(self._resp, Exception):
            raise self._resp
        return self._resp


def _patch(monkeypatch, resp):
    monkeypatch.setattr(ttl_uploader.httpx, "AsyncClient", lambda *a, **k: _Client(resp))


def _bindings(*pairs):
    return {
        "results": {"bindings": [{"t": {"value": t}, "n": {"value": str(n)}} for t, n in pairs]}
    }


BRICK = "https://brickschema.org/schema/Brick#"


class TestItReportsWhatCannotBeFixed:
    @pytest.mark.asyncio
    async def test_orphans_are_counted(self, monkeypatch):
        _patch(
            monkeypatch,
            _Resp(_bindings((BRICK + "Sound_Level_Sensor", 52), (BRICK + "Database", 2))),
        )
        out = await ttl_uploader.audit_undeclared_types()
        assert out["undeclared_types"] == 2
        assert out["instances"] == 54

    @pytest.mark.asyncio
    async def test_it_warns_loudly_enough_to_be_seen(self, monkeypatch, caplog):
        _patch(monkeypatch, _Resp(_bindings((BRICK + "Sound_Level_Sensor", 52))))
        with caplog.at_level("WARNING"):
            await ttl_uploader.audit_undeclared_types()
        msg = " ".join(r.message for r in caplog.records)
        assert "NOTHING declares" in msg
        assert "Sound_Level_Sensor" in msg

    @pytest.mark.asyncio
    async def test_the_worst_offenders_are_named(self, monkeypatch):
        pairs = [(BRICK + f"T{i}", 100 - i) for i in range(10)]
        _patch(monkeypatch, _Resp(_bindings(*pairs)))
        out = await ttl_uploader.audit_undeclared_types(sample=3)
        assert len(out["top"]) == 3
        assert out["top"][0]["count"] == 100


class TestACleanGraphSaysSo:
    @pytest.mark.asyncio
    async def test_zero_orphans_is_reported_not_silent(self, monkeypatch, caplog):
        """'Checked, found nothing' must not render like 'never checked'."""
        _patch(monkeypatch, _Resp(_bindings()))
        with caplog.at_level("INFO"):
            out = await ttl_uploader.audit_undeclared_types()
        assert out == {"undeclared_types": 0, "instances": 0, "top": []}
        assert "clean" in " ".join(r.message for r in caplog.records)


class TestItNeverBlocksStartup:
    @pytest.mark.asyncio
    async def test_a_graphdb_error_is_survivable(self, monkeypatch):
        _patch(monkeypatch, _Resp({}, status=503))
        assert (await ttl_uploader.audit_undeclared_types())["instances"] == 0

    @pytest.mark.asyncio
    async def test_an_exception_is_survivable(self, monkeypatch):
        _patch(monkeypatch, RuntimeError("graphdb down"))
        assert (await ttl_uploader.audit_undeclared_types())["instances"] == 0

    @pytest.mark.asyncio
    async def test_malformed_rows_are_skipped_not_fatal(self, monkeypatch):
        payload = {"results": {"bindings": [{"t": {"value": BRICK + "X"}}, {"n": {"value": "3"}}]}}
        _patch(monkeypatch, _Resp(payload))
        assert (await ttl_uploader.audit_undeclared_types())["undeclared_types"] == 0


class TestTheScopeIsWhatMakesItUsable:
    """First cut of this audit asked "what is outside every named graph?" and
    reported 1,576,783 findings — GraphDB's inferred superclass types and Brick's
    own SHACL vocabulary. A guard nobody can act on is worse than no guard
    (lessons.md #20). Scoping it to the namespaces this system MINTS into left
    exactly the 56 real ones."""

    @pytest.mark.asyncio
    async def test_the_query_is_scoped_to_owned_namespaces(self, monkeypatch):
        captured = {}

        class _Cap(_Client):
            async def post(self, *a, **k):
                captured["q"] = k.get("content") or (a[1] if len(a) > 1 else "")
                return _Resp(_bindings())

        monkeypatch.setattr(ttl_uploader.httpx, "AsyncClient", lambda *a, **k: _Cap(None))
        await ttl_uploader.audit_undeclared_types()
        q = captured["q"]
        assert "brickschema.org/schema/Brick#" in q
        assert "ontosage.org/capabilities#" in q
        assert "STRSTARTS" in q, "the namespace scope is missing"

    @pytest.mark.asyncio
    async def test_the_active_buildings_namespace_is_included(self, monkeypatch):
        from shared.config import settings

        monkeypatch.setattr(settings, "BUILDING_NAMESPACE", "http://example.org/mybldg#")
        captured = {}

        class _Cap(_Client):
            async def post(self, *a, **k):
                captured["q"] = k.get("content") or ""
                return _Resp(_bindings())

        monkeypatch.setattr(ttl_uploader.httpx, "AsyncClient", lambda *a, **k: _Cap(None))
        await ttl_uploader.audit_undeclared_types()
        assert "http://example.org/mybldg#" in captured["q"], "building namespace not scoped in"

    @pytest.mark.asyncio
    async def test_third_party_vocabulary_is_out_of_scope(self, monkeypatch):
        """SHACL terms are not declared here and are not this system's problem."""
        captured = {}

        class _Cap(_Client):
            async def post(self, *a, **k):
                captured["q"] = k.get("content") or ""
                return _Resp(_bindings())

        monkeypatch.setattr(ttl_uploader.httpx, "AsyncClient", lambda *a, **k: _Cap(None))
        await ttl_uploader.audit_undeclared_types()
        assert "www.w3.org/ns/shacl" not in captured["q"]
