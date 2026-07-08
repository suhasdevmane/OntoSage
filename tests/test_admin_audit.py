"""F2 — admin-action audit: the path/method filter deciding what gets audited."""

from types import SimpleNamespace

import pytest

import orchestrator.main as m

pytestmark = pytest.mark.unit


def _req(method: str, path: str) -> SimpleNamespace:
    return SimpleNamespace(method=method, url=SimpleNamespace(path=path))


def test_audits_mutating_admin_and_datasource_paths():
    assert m._should_audit_request(_req("POST", "/api/v1/admin/env"))
    assert m._should_audit_request(_req("PUT", "/api/v1/admin/role-access"))
    assert m._should_audit_request(_req("DELETE", "/api/v1/admin/databases/warehouse1"))
    assert m._should_audit_request(_req("POST", "/api/v1/datasources/noise/enable"))
    assert m._should_audit_request(_req("POST", "/api/v1/datasources/reset-demo"))


def test_does_not_audit_reads():
    # GET is not a mutation — including the audit endpoint itself.
    assert not m._should_audit_request(_req("GET", "/api/v1/admin/audit"))
    assert not m._should_audit_request(_req("GET", "/api/v1/datasources"))
    assert not m._should_audit_request(_req("GET", "/api/v1/admin/databases"))


def test_does_not_audit_unrelated_mutations():
    # Non-admin, non-datasource mutating paths are out of scope.
    assert not m._should_audit_request(_req("POST", "/chat"))
    assert not m._should_audit_request(_req("POST", "/auth/login"))
    assert not m._should_audit_request(_req("POST", "/v1/chat/completions"))
