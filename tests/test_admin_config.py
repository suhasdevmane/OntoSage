"""
Tests for admin_config — .env round-trip editing + DB connection overlay.

See tasks/IMPLEMENTATION_PLAN_DATASOURCE_TOGGLES_AND_PROVENANCE.md.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
import yaml

from orchestrator.services import admin_config as ac

pytestmark = pytest.mark.unit


SAMPLE_ENV = textwrap.dedent(
    """\
    # OntoSage env
    MODEL_PROVIDER=openai
    OPENAI_API_KEY=sk-realsecret
    REDIS_HOST=redis

    # a comment
    MYSQL_PASSWORD=hunter2
    DATASOURCE_TOGGLES_ENABLED=false
    """
)


def _env(tmp_path: Path) -> Path:
    p = tmp_path / ".env"
    p.write_text(SAMPLE_ENV, encoding="utf-8")
    return p


# ── secret detection ──────────────────────────────────────────────────────────


def test_is_secret():
    assert ac.is_secret("OPENAI_API_KEY")
    assert ac.is_secret("MYSQL_PASSWORD")
    assert ac.is_secret("SECRET_KEY")
    assert not ac.is_secret("REDIS_HOST")
    assert not ac.is_secret("MODEL_PROVIDER")


# ── read_env masks secrets ──────────────────────────────────────────────────────


def test_read_env_masks_secrets(tmp_path):
    rows = ac.read_env(_env(tmp_path))
    by = {r["key"]: r for r in rows}
    assert by["OPENAI_API_KEY"]["value"] == ac.MASK and by["OPENAI_API_KEY"]["is_secret"]
    assert by["MYSQL_PASSWORD"]["value"] == ac.MASK
    assert by["REDIS_HOST"]["value"] == "redis" and not by["REDIS_HOST"]["is_secret"]
    # comments/blank lines are not rows
    assert "# OntoSage env" not in [r["key"] for r in rows]


# ── apply_env round-trip ──────────────────────────────────────────────────────


def test_apply_env_updates_in_place_preserving_comments(tmp_path):
    p = _env(tmp_path)
    ac.apply_env({"REDIS_HOST": "redis2", "MODEL_PROVIDER": "local"}, p)
    text = p.read_text(encoding="utf-8")
    assert "REDIS_HOST=redis2" in text
    assert "MODEL_PROVIDER=local" in text
    assert "# OntoSage env" in text  # comment preserved
    assert "# a comment" in text
    # unchanged secret line intact
    assert "OPENAI_API_KEY=sk-realsecret" in text


def test_apply_env_skips_masked_secret(tmp_path):
    p = _env(tmp_path)
    ac.apply_env({"OPENAI_API_KEY": ac.MASK, "REDIS_HOST": "x"}, p)
    text = p.read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=sk-realsecret" in text  # NOT overwritten
    assert "REDIS_HOST=x" in text


def test_apply_env_overwrites_secret_when_new_value(tmp_path):
    p = _env(tmp_path)
    ac.apply_env({"MYSQL_PASSWORD": "newpass"}, p)
    assert "MYSQL_PASSWORD=newpass" in p.read_text(encoding="utf-8")


def test_apply_env_appends_new_key(tmp_path):
    p = _env(tmp_path)
    summary = ac.apply_env({"BRAND_NEW_KEY": "42"}, p)
    assert "BRAND_NEW_KEY" in summary["added"]
    assert "BRAND_NEW_KEY=42" in p.read_text(encoding="utf-8")


def test_apply_env_rejects_invalid_key(tmp_path):
    p = _env(tmp_path)
    summary = ac.apply_env({"bad key!": "x"}, p)
    assert any("invalid name" in s for s in summary["skipped"])
    assert "bad key!" not in p.read_text(encoding="utf-8")


# ── databases ─────────────────────────────────────────────────────────────────


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("REDIS_HOST=redis\n", encoding="utf-8")
    (tmp_path / "database_registry.yaml").write_text(
        yaml.safe_dump(
            {"databases": {"database1": {"type": "mysql", "host": "mysql", "password": "p"}}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(ac, "_ENV_SEARCH_PATHS", [tmp_path / ".env"])
    monkeypatch.setattr(ac, "_DB_PRIMARY_PATHS", [tmp_path / "database_registry.yaml"])
    return tmp_path


def test_read_databases_masks_password(db_env):
    dbs = {d["key"]: d for d in ac.read_databases()}
    assert dbs["database1"]["type"] == "mysql"
    assert dbs["database1"]["fields"]["password"] == ac.MASK
    assert dbs["database1"]["source"] == "curated"


def test_add_database_writes_overlay_and_env(db_env):
    res = ac.add_database("warehouse1", "postgresql", "db.host", "5432", "u", "secretpw", "sensors")
    assert res["ok"] and res["restart_required"]
    # overlay entry uses ${ENV} refs
    overlay = yaml.safe_load((db_env / "database_registry.custom.yaml").read_text(encoding="utf-8"))
    entry = overlay["databases"]["warehouse1"]
    assert entry["type"] == "postgresql"
    assert entry["host"] == "${WAREHOUSE1_HOST}"
    # credentials written to .env
    env = (db_env / ".env").read_text(encoding="utf-8")
    assert "WAREHOUSE1_HOST=db.host" in env
    assert "WAREHOUSE1_PASSWORD=secretpw" in env
    # appears in read_databases as custom
    dbs = {d["key"]: d for d in ac.read_databases()}
    assert dbs["warehouse1"]["source"] == "custom"


def test_add_database_rejects_duplicate(db_env):
    with pytest.raises(ValueError, match="already exists"):
        ac.add_database("database1", "mysql", "h", "3306", "u", "p", "d")


def test_add_database_rejects_bad_type(db_env):
    with pytest.raises(ValueError, match="unsupported type"):
        ac.add_database("x", "oracle", "h", "1521", "u", "p", "d")


# ── delete / resolve / probes ──────────────────────────────────────────────────


def test_delete_database_custom_only(db_env):
    ac.add_database("warehouse1", "postgresql", "h", "5432", "u", "p", "d")
    res = ac.delete_database("warehouse1")
    assert res["ok"] and res["key"] == "warehouse1"
    assert "warehouse1" not in [d["key"] for d in ac.read_databases()]


def test_delete_database_curated_protected(db_env):
    with pytest.raises(ValueError, match="GUI-added"):
        ac.delete_database("database1")  # curated — not in the custom overlay


def test_resolve_env_value():
    import os

    os.environ["ADMIN_CFG_TEST_HOST"] = "db.example.com"
    assert ac.resolve_env_value("${ADMIN_CFG_TEST_HOST}") == "db.example.com"
    assert ac.resolve_env_value("${NOT_SET_XYZ:-fallback}") == "fallback"
    assert ac.resolve_env_value("plain") == "plain"
    del os.environ["ADMIN_CFG_TEST_HOST"]


def test_resolve_connection(db_env, monkeypatch):
    ac.add_database("wh", "mysql", "db.host", "3306", "u", "p", "sensors")
    # add_database stores ${WH_*} refs in the registry + values in .env; at runtime
    # those live in os.environ (loaded by Docker). Simulate that here.
    monkeypatch.setenv("WH_HOST", "db.host")
    monkeypatch.setenv("WH_DATABASE", "sensors")
    c = ac.resolve_connection("wh")
    assert c["host"] == "db.host" and c["type"] == "mysql" and c["database"] == "sensors"


# ── CSV parsing ────────────────────────────────────────────────────────────────


def test_parse_sensor_csv_valid():
    pts, issues = ac.parse_sensor_csv(
        "local,brick_class,location,uuid,unit\nS1,brick:Temperature_Sensor,bldg:Z,u-1,unit:DEG_C"
    )
    assert issues == [] and len(pts) == 1
    assert pts[0]["uuid"] == "u-1" and pts[0]["unit"] == "unit:DEG_C"


def test_parse_sensor_csv_missing_columns():
    pts, issues = ac.parse_sensor_csv("local,uuid\nS1,u1")
    assert pts == [] and any("missing columns" in i for i in issues)


def test_parse_sensor_csv_row_missing_field():
    pts, issues = ac.parse_sensor_csv(
        "local,brick_class,location,uuid\nS1,brick:T,bldg:Z,u1\nS2,,bldg:Z,u2"
    )
    assert len(pts) == 1 and any("row 3" in i for i in issues)


# ── live probes (drivers monkeypatched — no real DB) ──────────────────────────


class _MyCur:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, q, *a):
        self.q = q

    def fetchone(self):
        if "COUNT(DISTINCT" in self.q:
            return (5,)
        if "COUNT(*)" in self.q:
            return (100,)
        return (1,)

    def fetchall(self):
        if "SHOW TABLES" in self.q:
            return [("occupancy_data",)]
        if "SHOW COLUMNS" in self.q:
            return [("uuid", "char(36)"), ("datetime", "datetime"), ("value", "double")]
        if "ORDER BY" in self.q:
            return [("u1", "2026-01-01 00:00:00", 42.0)]
        return []

    def close(self):
        pass


class _MyConn:
    def cursor(self):
        return _MyCur()

    def close(self):
        pass


@pytest.fixture
def fake_mysql(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(ac, "_pymysql", SimpleNamespace(connect=lambda **k: _MyConn()))
    return None


@pytest.mark.asyncio
async def test_test_connection_mysql_ok(fake_mysql):
    res = await ac.test_connection("mysql", "h", "3306", "u", "p", "d")
    assert res["ok"] is True and "latency_ms" in res


@pytest.mark.asyncio
async def test_test_connection_unsupported():
    res = await ac.test_connection("oracle", "h", "1521", "u", "p", "d")
    assert res["ok"] is False and "unsupported" in res["error"]


@pytest.mark.asyncio
async def test_test_connection_error(monkeypatch):
    from types import SimpleNamespace

    def _boom(**k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ac, "_pymysql", SimpleNamespace(connect=_boom))
    res = await ac.test_connection("mysql", "h", "3306", "u", "p", "d")
    assert res["ok"] is False and "refused" in res["error"]


@pytest.mark.asyncio
async def test_introspect_mysql(fake_mysql):
    res = await ac.introspect("mysql", "h", "3306", "u", "p", "d")
    assert res["ok"] and res["tables"][0]["name"] == "occupancy_data"
    assert {c["name"] for c in res["tables"][0]["columns"]} == {"uuid", "datetime", "value"}


@pytest.mark.asyncio
async def test_table_stats_mysql(fake_mysql):
    res = await ac.table_stats("mysql", "h", "3306", "u", "p", "d", "occupancy_data")
    assert res["ok"] and res["rows"] == 100 and res["sensors"] == 5
    assert res["sample"][0]["uuid"] == "u1"


@pytest.mark.asyncio
async def test_table_stats_rejects_bad_table(fake_mysql):
    res = await ac.table_stats("mysql", "h", "3306", "u", "p", "d", "bad table;drop")
    assert res["ok"] is False


class _PGConn:
    async def fetchval(self, q, *a):
        if "COUNT(DISTINCT" in q:
            return 5
        if "COUNT(*)" in q:
            return 100
        return 1

    async def fetch(self, q, *a):
        if "information_schema" in q:
            return [{"table_name": "t", "column_name": "uuid", "data_type": "uuid"}]
        return [{"uuid": "u1", "datetime": "t", "value": 1.0}]

    async def close(self):
        pass


def test_active_db_keys(tmp_path):
    (tmp_path / "building.yaml").write_text(
        yaml.safe_dump({"storage": {"databases": ["database1", "energy_data"]}}), encoding="utf-8"
    )
    assert ac.active_db_keys(tmp_path) == {"database1", "energy_data"}


def test_active_db_keys_none_when_no_filter(tmp_path):
    (tmp_path / "building.yaml").write_text(
        yaml.safe_dump({"storage": {"databases": []}}), encoding="utf-8"
    )
    assert ac.active_db_keys(tmp_path) is None
    # no building.yaml at all -> None
    assert ac.active_db_keys(tmp_path / "empty") is None


@pytest.mark.asyncio
async def test_test_connection_pg_ok(monkeypatch):
    from types import SimpleNamespace

    async def _c(**k):
        return _PGConn()

    monkeypatch.setattr(ac, "_asyncpg", SimpleNamespace(connect=_c))
    res = await ac.test_connection("postgresql", "h", "5432", "u", "p", "d")
    assert res["ok"] is True


# ── role → data-source access ──────────────────────────────────────────────────


@pytest.fixture
def role_env(tmp_path, monkeypatch):
    monkeypatch.setattr(ac, "_input_dir", lambda: tmp_path)
    return tmp_path


def test_admin_always_allowed(role_env):
    # even with an explicit deny, admin bypasses
    ac.set_role_access("admin", [])
    assert ac.is_source_allowed("admin", "occupancy") is True


def test_unlisted_role_is_permissive(role_env):
    # no file / role absent → allowed (access control is opt-in)
    assert ac.is_source_allowed("analyst", "occupancy") is True


def test_set_and_enforce_role_allow_list(role_env):
    ac.set_role_access("readonly", ["occupancy"])
    assert ac.is_source_allowed("readonly", "occupancy") is True
    assert ac.is_source_allowed("readonly", "energy") is False


def test_star_allows_all(role_env):
    ac.set_role_access("occupant", "*")
    assert ac.is_source_allowed("occupant", "anything") is True


def test_role_access_persisted_and_reloaded(role_env):
    ac.set_role_access("readonly", ["noise"])
    reloaded = ac.read_role_access()
    assert reloaded["readonly"] == ["noise"]


def test_empty_allow_list_blocks_everything(role_env):
    # [] must mean "no access" (not permissive) — the readonly-role hardening.
    ac.set_role_access("readonly", [])
    assert ac.is_source_allowed("readonly", "occupancy") is False
    assert ac.is_source_allowed("readonly", "noise") is False


# ── F3 hardening: newline injection, embedded-credential masking ─────────────────


def test_apply_env_rejects_newline_in_value(tmp_path):
    # A value with CR/LF must not inject extra KEY=value lines into .env.
    p = _env(tmp_path)
    summary = ac.apply_env({"REDIS_HOST": "ok\nADMIN_PASSWORD=pwned"}, p)
    text = p.read_text(encoding="utf-8")
    assert "ADMIN_PASSWORD=pwned" not in text
    assert any("REDIS_HOST" in s for s in summary["skipped"])
    # the original value is left untouched
    assert "REDIS_HOST=redis" in text


def test_value_has_embedded_credentials():
    assert ac.value_has_embedded_credentials("redis://user:pass@host:6379/0")
    assert ac.value_has_embedded_credentials("mongodb://admin:s3cret@mongo:27017")
    assert not ac.value_has_embedded_credentials("redis://redis:6379/0")
    assert not ac.value_has_embedded_credentials("plainvalue")


def test_read_env_masks_value_with_embedded_credentials(tmp_path):
    # A URL/DSN with inline user:pass@ must be masked even if the key name has no
    # secret token (REDIS_URL / MONGODB_URI / DATABASE_URL).
    p = tmp_path / ".env"
    p.write_text(
        "REDIS_URL=redis://user:pass@host:6379/0\nPLAIN_URL=http://svc:8000\n",
        encoding="utf-8",
    )
    by = {r["key"]: r for r in ac.read_env(p)}
    assert by["REDIS_URL"]["value"] == ac.MASK and by["REDIS_URL"]["is_secret"]
    assert by["PLAIN_URL"]["value"] == "http://svc:8000" and not by["PLAIN_URL"]["is_secret"]


# ── F4: config backup / restore ──────────────────────────────────────────────────


@pytest.fixture
def backup_env(tmp_path, monkeypatch):
    """Point the managed-config targets at a tmp dir so tests never touch real files."""
    targets = {
        "datasources.custom.yaml": tmp_path / "datasources.custom.yaml",
        "role_datasource_access.yaml": tmp_path / "role_datasource_access.yaml",
        "datasource_state.json": tmp_path / "state.json",
    }
    monkeypatch.setattr(ac, "_managed_config_targets", lambda: dict(targets))
    return tmp_path, targets


def test_backup_collects_present_files_only(backup_env):
    _, targets = backup_env
    targets["datasources.custom.yaml"].write_text("datasources: []\n", encoding="utf-8")
    b = ac.backup_config()
    assert b["meta"]["kind"] == "ontosage-console-config"
    assert b["files"]["datasources.custom.yaml"] == "datasources: []\n"
    assert b["files"]["role_datasource_access.yaml"] is None  # absent → null


def test_backup_never_includes_env_secrets(backup_env):
    b = ac.backup_config()
    assert not any(".env" in k.lower() for k in b["files"])


def test_restore_round_trip(backup_env):
    _, targets = backup_env
    bundle = {"files": {"role_datasource_access.yaml": "roles:\n  readonly: []\n"}}
    summary = ac.restore_config(bundle)
    assert "role_datasource_access.yaml" in summary["restored"]
    assert targets["role_datasource_access.yaml"].read_text(encoding="utf-8") == (
        "roles:\n  readonly: []\n"
    )


def test_restore_is_atomic_on_invalid_yaml(backup_env):
    _, targets = backup_env
    bundle = {
        "files": {
            "role_datasource_access.yaml": "roles:\n  readonly: []\n",  # valid
            "datasources.custom.yaml": "datasources: [unclosed",  # invalid YAML
        }
    }
    with pytest.raises(ValueError, match="(?i)invalid"):
        ac.restore_config(bundle)
    # atomic: the valid file must NOT have been written
    assert not targets["role_datasource_access.yaml"].exists()


def test_restore_dry_run_writes_nothing(backup_env):
    _, targets = backup_env
    bundle = {"files": {"role_datasource_access.yaml": "roles: {}\n"}}
    summary = ac.restore_config(bundle, dry_run=True)
    assert summary.get("dry_run") is True
    assert "role_datasource_access.yaml" in summary["restored"]
    assert not targets["role_datasource_access.yaml"].exists()


def test_restore_skips_unknown_targets(backup_env):
    # An unknown key (e.g. a smuggled .env) is skipped, not written.
    summary = ac.restore_config({"files": {".env": "SECRET=x\n"}})
    assert any(".env" in s for s in summary["skipped"])
    assert summary["restored"] == []


def test_restore_rejects_malformed_bundle(backup_env):
    with pytest.raises(ValueError, match="(?i)files"):
        ac.restore_config({"meta": {}})
