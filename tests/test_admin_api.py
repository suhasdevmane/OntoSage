"""
Endpoint tests for the admin console (.env + databases). admin_config is
monkeypatched so the real root .env is never touched.
"""

from __future__ import annotations

import pytest

import orchestrator.main as m
from orchestrator.services import admin_config as ac
from orchestrator.services import db_ontology as dbo

pytestmark = pytest.mark.unit


async def _aval(v):
    return v


@pytest.mark.asyncio
async def test_get_env(monkeypatch):
    monkeypatch.setattr(
        ac,
        "read_env",
        lambda *a, **k: [{"key": "REDIS_HOST", "value": "redis", "is_secret": False}],
    )
    resp = await m.get_env(user=None)
    assert resp.success is True
    assert resp.data["env"][0]["key"] == "REDIS_HOST"
    assert resp.data["mask"] == ac.MASK


@pytest.mark.asyncio
async def test_put_env_reports_restart_required(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        ac,
        "apply_env",
        lambda ch: captured.setdefault("ch", ch)
        or {"updated": list(ch), "added": [], "skipped": []},
    )
    monkeypatch.setattr(ac, "env_path", lambda: "/app/.env")
    body = m.EnvUpdate(changes={"REDIS_HOST": "redis2"})
    resp = await m.put_env(body=body, user=None)
    assert resp.success is True
    assert resp.data["restart_required"] is True
    assert captured["ch"] == {"REDIS_HOST": "redis2"}


@pytest.mark.asyncio
async def test_get_databases(monkeypatch):
    monkeypatch.setattr(
        ac,
        "read_databases",
        lambda: [
            {"key": "database1", "type": "mysql", "fields": {}, "source": "curated"},
            {"key": "neon", "type": "postgresql", "fields": {}, "source": "curated"},
        ],
    )
    monkeypatch.setattr(ac, "active_db_keys", lambda *a: {"database1"})
    resp = await m.get_databases(user=None)
    assert resp.success is True and resp.data["filtered"] is True
    by = {d["key"]: d for d in resp.data["databases"]}
    assert by["database1"]["active"] is True and by["neon"]["active"] is False


@pytest.mark.asyncio
async def test_create_database_ok(monkeypatch):
    monkeypatch.setattr(
        ac, "add_database", lambda *a, **k: {"ok": True, "key": a[0], "restart_required": True}
    )
    body = m.DatabaseCreate(
        key="warehouse1",
        type="postgresql",
        host="h",
        port="5432",
        user="u",
        password="p",
        database="d",
    )
    resp = await m.create_database(body=body, user=None)
    assert resp.success is True and resp.data["key"] == "warehouse1"


@pytest.mark.asyncio
async def test_create_database_error(monkeypatch):
    def _boom(*a, **k):
        raise ValueError("database key 'database1' already exists")

    monkeypatch.setattr(ac, "add_database", _boom)
    body = m.DatabaseCreate(key="database1", type="mysql", host="h")
    resp = await m.create_database(body=body, user=None)
    assert resp.success is False and "already exists" in resp.error


# ── user management ────────────────────────────────────────────────────────────


class _PG:
    def __init__(self):
        self.deleted = None
        self.role_set = None

    async def list_users(self):
        return [{"username": "admin", "role": "admin", "email": None}]

    async def update_user_role(self, username, role):
        self.role_set = (username, role)
        return True

    async def delete_user(self, username):
        self.deleted = username
        return True


class _Auth:
    async def register_user(self, u, p, e=None, role="readonly"):
        return {"success": True}


@pytest.mark.asyncio
async def test_list_users(monkeypatch):
    monkeypatch.setattr(m, "postgres_manager", _PG())
    resp = await m.list_users(user=None)
    assert resp.success is True
    assert resp.data["users"][0]["username"] == "admin"
    assert "readonly" in resp.data["roles"]


@pytest.mark.asyncio
async def test_create_user_ok(monkeypatch):
    monkeypatch.setattr(m, "auth_manager", _Auth())
    body = m.UserCreate(username="alice", password="secret123456", role="analyst")
    resp = await m.create_user_account(body=body, user=None)
    assert resp.success is True and resp.data["role"] == "analyst"


@pytest.mark.asyncio
async def test_create_user_invalid_role(monkeypatch):
    monkeypatch.setattr(m, "auth_manager", _Auth())
    body = m.UserCreate(username="alice", password="secret123456", role="wizard")
    resp = await m.create_user_account(body=body, user=None)
    assert resp.success is False and "invalid role" in resp.error


@pytest.mark.asyncio
async def test_update_role(monkeypatch):
    pg = _PG()
    monkeypatch.setattr(m, "postgres_manager", pg)
    resp = await m.update_user_role("alice", m.RoleUpdate(role="operator"), user=None)
    assert resp.success is True and pg.role_set == ("alice", "operator")


@pytest.mark.asyncio
async def test_delete_user_blocks_self(monkeypatch):
    from types import SimpleNamespace

    pg = _PG()
    monkeypatch.setattr(m, "postgres_manager", pg)
    me = SimpleNamespace(username="admin")
    resp = await m.delete_user_account("admin", user=me)
    assert resp.success is False and pg.deleted is None


@pytest.mark.asyncio
async def test_restart_endpoint_schedules_sigterm(monkeypatch):
    import asyncio

    killed = {}
    monkeypatch.setattr(m.os, "kill", lambda pid, sig: killed.setdefault("call", (pid, sig)))
    resp = await m.restart_orchestrator(user=None)
    assert resp.success is True and resp.data["restarting"] is True
    await asyncio.sleep(0.85)  # let the delayed self-terminate task fire (monkeypatched)
    assert "call" in killed


@pytest.mark.asyncio
async def test_db_sensors_count(monkeypatch):
    async def _count(k, **kw):
        return 5

    monkeypatch.setattr(dbo, "graph_triple_count", _count)
    resp = await m.get_db_sensors("warehouse1", user=None)
    assert resp.success is True and resp.data["triples"] == 5


@pytest.mark.asyncio
async def test_register_db_sensors_points(monkeypatch):
    async def _reg(key, points, **kw):
        return {"ok": True, "db_key": key, "points": len(points), "graph": "g"}

    monkeypatch.setattr(dbo, "register_points", _reg)
    monkeypatch.setattr(m.app.state, "response_cache", None, raising=False)
    body = m.SensorPoints(
        points=[
            {
                "local": "S1",
                "brick_class": "brick:Temperature_Sensor",
                "location": "bldg:Z",
                "uuid": "u",
            }
        ]
    )
    resp = await m.register_db_sensors("warehouse1", body, user=None)
    assert resp.success is True and resp.data["points"] == 1


@pytest.mark.asyncio
async def test_register_db_sensors_ttl(monkeypatch):
    async def _reg(key, ttl, **kw):
        return {"ok": True, "db_key": key, "graph": "g", "warnings": []}

    monkeypatch.setattr(dbo, "register_ttl", _reg)
    monkeypatch.setattr(m.app.state, "response_cache", None, raising=False)
    body = m.SensorTtl(ttl="@prefix bldg: <http://x#> . bldg:S1 a brick:Sensor .")
    resp = await m.register_db_sensors_ttl("warehouse1", body, user=None)
    assert resp.success is True


@pytest.mark.asyncio
async def test_register_db_sensors_reports_failure(monkeypatch):
    async def _reg(key, points, **kw):
        return {"ok": False, "error": "point[0]: missing 'uuid'"}

    monkeypatch.setattr(dbo, "register_points", _reg)
    body = m.SensorPoints(points=[{"local": "S1"}])
    resp = await m.register_db_sensors("warehouse1", body, user=None)
    assert resp.success is False and "uuid" in resp.error


@pytest.mark.asyncio
async def test_test_database_by_creds(monkeypatch):
    async def _tc(t, h, p, u, pw, d):
        return {"ok": True, "latency_ms": 12.3}

    monkeypatch.setattr(ac, "test_connection", _tc)
    body = m.ConnProbe(type="mysql", host="h", user="u", password="p", database="d")
    resp = await m.test_database(body=body, user=None)
    assert resp.success is True and resp.data["latency_ms"] == 12.3


@pytest.mark.asyncio
async def test_test_database_by_key(monkeypatch):
    async def _tc(*a):
        return {"ok": True}

    monkeypatch.setattr(
        ac,
        "resolve_connection",
        lambda k: {
            "type": "mysql",
            "host": "h",
            "port": "3306",
            "user": "u",
            "password": "p",
            "database": "d",
        },
    )
    monkeypatch.setattr(ac, "test_connection", _tc)
    resp = await m.test_database(body=m.ConnProbe(key="database1"), user=None)
    assert resp.success is True


@pytest.mark.asyncio
async def test_test_database_unknown_key(monkeypatch):
    monkeypatch.setattr(ac, "resolve_connection", lambda k: None)
    resp = await m.test_database(body=m.ConnProbe(key="nope"), user=None)
    assert resp.success is False and "unknown" in resp.error


@pytest.mark.asyncio
async def test_introspect_database(monkeypatch):
    async def _in(*a):
        return {"ok": True, "tables": [{"name": "t", "columns": []}]}

    monkeypatch.setattr(ac, "introspect", _in)
    resp = await m.introspect_database(body=m.ConnProbe(type="mysql", host="h"), user=None)
    assert resp.success is True and resp.data["tables"][0]["name"] == "t"


@pytest.mark.asyncio
async def test_table_stats_endpoint(monkeypatch):
    async def _ts(*a):
        return {"ok": True, "rows": 100, "sensors": 5, "sample": []}

    monkeypatch.setattr(
        ac,
        "resolve_connection",
        lambda k: {
            "type": "mysql",
            "host": "h",
            "port": "3306",
            "user": "u",
            "password": "p",
            "database": "d",
        },
    )
    monkeypatch.setattr(ac, "table_stats", _ts)
    resp = await m.database_table_stats("occupancy_data", table="occupancy_data", user=None)
    assert resp.success is True and resp.data["rows"] == 100


@pytest.mark.asyncio
async def test_delete_database_endpoint(monkeypatch):
    monkeypatch.setattr(ac, "delete_database", lambda k: {"ok": True, "key": k})

    async def _clear(k):
        return True

    monkeypatch.setattr(dbo, "clear_graph", _clear)
    resp = await m.delete_database_conn("warehouse1", user=None)
    assert resp.success is True and resp.data["key"] == "warehouse1"


@pytest.mark.asyncio
async def test_delete_database_curated_blocked(monkeypatch):
    def _boom(k):
        raise ValueError("'database1' is not GUI-added")

    monkeypatch.setattr(ac, "delete_database", _boom)
    resp = await m.delete_database_conn("database1", user=None)
    assert resp.success is False and "GUI-added" in resp.error


@pytest.mark.asyncio
async def test_register_db_sensors_csv(monkeypatch):
    monkeypatch.setattr(
        ac,
        "parse_sensor_csv",
        lambda t: (
            [{"local": "S1", "brick_class": "brick:T", "location": "bldg:Z", "uuid": "u"}],
            [],
        ),
    )

    async def _reg(key, points, **kw):
        return {"ok": True, "points": len(points)}

    monkeypatch.setattr(dbo, "register_points", _reg)
    monkeypatch.setattr(m.app.state, "response_cache", None, raising=False)
    resp = await m.register_db_sensors_csv("warehouse1", m.SensorCsv(csv="x"), user=None)
    assert resp.success is True and resp.data["points"] == 1


@pytest.mark.asyncio
async def test_register_db_sensors_csv_bad(monkeypatch):
    monkeypatch.setattr(ac, "parse_sensor_csv", lambda t: ([], ["missing columns: ['uuid']"]))
    resp = await m.register_db_sensors_csv("warehouse1", m.SensorCsv(csv="x"), user=None)
    assert resp.success is False and "missing" in resp.error


@pytest.mark.asyncio
async def test_role_access_get_and_put(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ac, "read_role_access", lambda: {"readonly": ["occupancy"]})
    monkeypatch.setattr(
        ac, "set_role_access", lambda role, src: {"ok": True, "role": role, "sources": src}
    )
    reg = SimpleNamespace(
        list=lambda: [SimpleNamespace(id="occupancy"), SimpleNamespace(id="energy")]
    )
    monkeypatch.setattr(m.app.state, "datasource_registry", reg, raising=False)
    get = await m.get_role_access(user=None)
    assert get.success and set(get.data["sources"]) == {"occupancy", "energy"}
    put = await m.put_role_access(
        body=m.RoleAccessUpdate(role="readonly", sources=["occupancy"]), user=None
    )
    assert put.success is True
