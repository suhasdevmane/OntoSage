"""Automatic backups: coalescing, retention, failure isolation, export, round trip, passphrase.

No live database and no Docker. Time is injected (a fake clock whose sleep advances it), so the
scheduling tests are deterministic. The archive round trip goes through the host restore code,
which is the same format the container writes.
"""

import ast
import asyncio
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _backup_format as fmt  # noqa: E402  (the host alias of the same file)
import restore_encrypted as rs  # noqa: E402

from orchestrator.services import auto_backup as auto  # noqa: E402
from orchestrator.services import backup_format  # noqa: E402

pytestmark = pytest.mark.unit

GOOD = "a long enough passphrase"
SECRET_LINE = "POSTGRES_USER_PASSWORD=do-not-leak-this-value"


class FakeClock:
    """A monotonic clock whose sleep advances it instantly."""

    def __init__(self, start: float = 1000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    async def sleep(self, seconds: float) -> None:
        self.t += seconds
        await asyncio.sleep(0)


def _service(tmp_path: Path, clock: FakeClock, **overrides) -> auto.AutoBackupService:
    kwargs = dict(
        enabled=True,
        passphrase=GOOD,
        out_dir=tmp_path / "out",
        min_interval_s=600,
        keep=96,
        pool_getter=lambda: None,
        app_root=tmp_path / "app",
        building_id="bldg1",
        settle_s=0,
        clock=clock,
        sleep=clock.sleep,
    )
    kwargs.update(overrides)
    return auto.AutoBackupService(**kwargs)


def _recording_run(svc: auto.AutoBackupService, clock: FakeClock) -> list:
    runs: list = []

    async def fake_run() -> None:
        runs.append(clock())

    svc._run_once = fake_run  # type: ignore[assignment]
    return runs


# ---------- coalescing ----------


async def test_many_requests_in_one_interval_produce_one_run(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock)
    runs = _recording_run(svc, clock)
    for _ in range(50):
        svc.request()
    await svc._worker
    assert len(runs) == 1


async def test_requests_during_an_interval_run_once_when_it_ends(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock)
    runs = _recording_run(svc, clock)
    start = clock()
    svc.request()
    await svc._worker
    for _ in range(30):
        svc.request()
    await svc._worker
    assert runs == [start, start + 600]


async def test_a_request_after_the_interval_runs_at_once(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock)
    runs = _recording_run(svc, clock)
    svc.request()
    await svc._worker
    clock.t += 700
    svc.request()
    await svc._worker
    assert len(runs) == 2
    assert runs[1] - runs[0] >= 600


async def test_no_request_no_run(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock)
    runs = _recording_run(svc, clock)
    await asyncio.sleep(0)
    assert runs == []
    assert svc._worker is None


# ---------- enablement: passphrase only ----------


def test_no_passphrase_means_disabled_and_requests_do_nothing(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock, passphrase="")
    assert svc.enabled is False
    svc.request()
    assert svc._worker is None


def test_a_passphrase_shorter_than_the_minimum_disables_the_service(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock, passphrase="short")
    assert svc.enabled is False


def test_disabled_by_flag_even_with_a_passphrase(tmp_path):
    clock = FakeClock()
    assert _service(tmp_path, clock, enabled=False).enabled is False


def test_the_passphrase_comes_from_settings_and_nowhere_else():
    source = (REPO / "orchestrator" / "services" / "auto_backup.py").read_text(encoding="utf-8")
    assert "keyring" not in source
    assert "settings.BACKUP_PASSPHRASE" in source
    assert "getpass" not in source


# ---------- failure handling ----------


async def test_a_missing_database_is_logged_and_counted_not_raised(tmp_path, caplog):
    clock = FakeClock()
    svc = _service(tmp_path, clock)  # pool_getter returns None
    await svc._run_once()
    assert svc.failures == 1 and svc.successes == 0
    assert "backup FAILED" in caplog.text
    assert "PostgreSQL is not connected" in caplog.text


async def test_a_write_error_is_counted_and_leaves_no_partial_file(tmp_path, monkeypatch):
    clock = FakeClock()
    svc = _service(tmp_path, clock, pool_getter=lambda: object())

    async def fake_export(pool, staging):
        p = staging / "users.jsonl"
        p.write_text('{"id": 1}\n', encoding="utf-8")
        return [("db/postgres/users.jsonl", p)]

    def broken_write(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(auto, "export_postgres", fake_export)
    monkeypatch.setattr(auto, "write_archive", broken_write)
    await svc._run_once()  # must not raise
    assert svc.failures == 1
    assert not list((tmp_path / "out").glob("*.partial"))
    assert not list((tmp_path / "out").glob("ontosage-auto-*.enc"))


async def test_the_answer_path_survives_a_failing_request(tmp_path):
    clock = FakeClock()
    svc = _service(tmp_path, clock)
    svc.request()  # pool is None, so the run fails inside its own try block
    await svc._worker
    assert svc.failures == 1


def test_status_carries_no_error_text_because_health_is_unauthenticated(tmp_path):
    clock = FakeClock()
    status = _service(tmp_path, clock).status()
    assert set(status) == {
        "enabled",
        "last_success_utc",
        "last_success_age_s",
        "last_attempt_utc",
        "successes",
        "failures",
        "pending",
        "min_interval_s",
        "keep",
    }


# ---------- retention ----------


def _touch(path: Path, body: bytes = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def test_retention_keeps_the_newest_n_and_touches_only_automatic_archives(tmp_path):
    out = tmp_path / "out"
    for day in range(1, 6):
        _touch(out / f"ontosage-auto-2026010{day}T000000Z.enc")
    _touch(out / "ontosage-20260101T000000Z.enc")  # routine archive: not ours to delete
    _touch(out / "notes.txt")
    _touch(out / "ontosage-auto-20260109T000000Z.enc.partial")
    deleted = auto.prune_auto(out, keep=2)
    assert sorted(p.name for p in deleted) == [
        "ontosage-auto-20260101T000000Z.enc",
        "ontosage-auto-20260102T000000Z.enc",
        "ontosage-auto-20260103T000000Z.enc",
    ]
    assert sorted(p.name for p in out.iterdir()) == [
        "notes.txt",
        "ontosage-20260101T000000Z.enc",
        "ontosage-auto-20260104T000000Z.enc",
        "ontosage-auto-20260105T000000Z.enc",
        "ontosage-auto-20260109T000000Z.enc.partial",
    ]


def test_retention_never_deletes_the_only_archive_even_when_misconfigured(tmp_path):
    out = tmp_path / "out"
    _touch(out / "ontosage-auto-20260101T000000Z.enc")
    _touch(out / "ontosage-auto-20260102T000000Z.enc")
    assert len(auto.prune_auto(out, keep=0)) == 1
    assert [p.name for p in out.glob("ontosage-auto-*.enc")] == [
        "ontosage-auto-20260102T000000Z.enc"
    ]


def test_routine_retention_skips_automatic_archives(tmp_path):
    import backup_encrypted as be

    out = tmp_path / "out"
    _touch(out / "ontosage-20260101T000000Z.enc")
    _touch(out / "ontosage-20260102T000000Z.enc")
    _touch(out / "ontosage-auto-20260101T000000Z.enc")
    _touch(out / "ontosage-auto-20260102T000000Z.enc")
    be.prune(out, keep=1)
    names = sorted(p.name for p in out.glob("*.enc"))
    assert "ontosage-auto-20260101T000000Z.enc" in names
    assert "ontosage-auto-20260102T000000Z.enc" in names
    assert "ontosage-20260102T000000Z.enc" in names
    assert "ontosage-20260101T000000Z.enc" not in names


# ---------- export and config collection ----------


class _AsyncRows:
    def __init__(self, rows):
        self._rows = iter(rows)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._rows)
        except StopIteration:
            raise StopAsyncIteration


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeConn:
    def __init__(self, tables, log):
        self._tables = tables
        self._log = log

    def transaction(self, isolation=None):
        self._log.append(("isolation", isolation))
        return _Tx()

    async def fetch(self, query):
        self._log.append(("fetch", query))
        return [{"tablename": t} for t in self._tables]

    def cursor(self, query):
        self._log.append(("cursor", query))
        return _AsyncRows([{"j": json.dumps({"id": 1, "table": query})}])


class _Acquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *exc):
        return False


class _FakePool:
    def __init__(self, tables):
        self.log = []
        self._conn = _FakeConn(tables, self.log)

    def acquire(self):
        return _Acquire(self._conn)


async def test_export_writes_every_public_table_with_quoted_names(tmp_path):
    pool = _FakePool(["users", 'odd"name'])
    members = await auto.export_postgres(pool, tmp_path)
    arcs = [arc for arc, _ in members]
    # The archive name is sanitised; the SQL still uses the exact, quoted identifier.
    assert arcs == ["db/postgres/000_users.jsonl", "db/postgres/001_odd_name.jsonl"]
    cursors = [q for kind, q in pool.log if kind == "cursor"]
    assert 'FROM "odd""name" AS t' in cursors[1]
    assert ("isolation", "repeatable_read") in pool.log
    lines = members[0][1].read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["id"] == 1


def test_config_collection_takes_input_and_env_and_records_absences(tmp_path):
    (tmp_path / "input" / "sub").mkdir(parents=True)
    (tmp_path / "input" / "bldg1_x.ttl").write_text("@prefix x: <urn:x> .", encoding="utf-8")
    (tmp_path / "input" / "sub" / "m.yaml").write_text("a: 1", encoding="utf-8")
    (tmp_path / ".env").write_text(SECRET_LINE + "\n", encoding="utf-8")
    members, skipped = auto.config_members(tmp_path)
    assert sorted(arc for arc, _ in members) == [
        "config/env",
        "config/input/bldg1_x.ttl",
        "config/input/sub/m.yaml",
    ]
    assert skipped == []

    members, skipped = auto.config_members(tmp_path / "nowhere")
    assert members == []
    assert {s["source"] for s in skipped} == {"config/input", "config/env"}


# ---------- round trip ----------


async def test_archive_round_trips_through_the_restore_code(tmp_path, monkeypatch):
    clock = FakeClock()
    app = tmp_path / "app"
    (app / "input").mkdir(parents=True)
    (app / "input" / "bldg1_x.ttl").write_text("@prefix x: <urn:x> .", encoding="utf-8")
    (app / ".env").write_text(SECRET_LINE + "\n", encoding="utf-8")

    async def fake_export(pool, staging):
        p = staging / "users.jsonl"
        p.write_text('{"username": "occupant01"}\n', encoding="utf-8")
        return [("db/postgres/users.jsonl", p)]

    monkeypatch.setattr(auto, "export_postgres", fake_export)
    svc = _service(tmp_path, clock, pool_getter=lambda: object(), app_root=app)
    await svc._run_once()
    assert svc.successes == 1, "run must succeed for this test to mean anything"

    archives = sorted((tmp_path / "out").glob("ontosage-auto-*.enc"))
    assert len(archives) == 1
    archive = archives[0]

    # The secret must not be readable in the archive bytes, only inside the encryption.
    assert b"do-not-leak-this-value" not in archive.read_bytes()

    dest = tmp_path / "restored"
    dest.mkdir()
    manifest = rs.extract_and_verify(archive, GOOD, dest)
    assert manifest["scope"] == "automatic"
    assert manifest["building_id"] == "bldg1"
    assert (dest / "config" / "input" / "bldg1_x.ttl").read_text(encoding="utf-8") == (
        "@prefix x: <urn:x> ."
    )
    assert SECRET_LINE in (dest / "config" / "env").read_text(encoding="utf-8")
    assert json.loads((dest / "db" / "postgres" / "users.jsonl").read_text().strip()) == {
        "username": "occupant01"
    }
    assert {s["source"] for s in manifest["skipped"]} == set()

    with pytest.raises(fmt.ArchiveAuthError):
        rs.extract_and_verify(archive, "the wrong passphrase value", tmp_path / "wrong")


# ---------- the format module stays importable from the host ----------


def test_the_format_module_imports_only_stdlib_and_cryptography():
    tree = ast.parse((REPO / "orchestrator" / "services" / "backup_format.py").read_text("utf-8"))
    allowed = {
        "gzip",
        "hashlib",
        "io",
        "json",
        "os",
        "struct",
        "tarfile",
        "time",
        "pathlib",
        "typing",
        "cryptography",
    }
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert roots <= allowed, roots - allowed


def test_the_host_alias_agrees_with_the_container_module_on_the_format():
    # The alias is a second module object, so class identity cannot match. What must match is
    # the format: the constants, and an archive written by one reading back through the other.
    assert fmt.MIN_PASSPHRASE_LENGTH == backup_format.MIN_PASSPHRASE_LENGTH == 12
    assert fmt.MAGIC == backup_format.MAGIC and fmt.HEADER_LEN == backup_format.HEADER_LEN
