"""Encrypted backup archive: round trip, tamper detection, manifest checks, retention, dry run.

All archives are synthetic and written into tmp_path. Nothing touches a database or Docker.
"""

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import _backup_format as fmt  # noqa: E402
import _backup_secret as sec  # noqa: E402
import backup_encrypted as be  # noqa: E402
import restore_encrypted as rs  # noqa: E402

pytestmark = pytest.mark.unit

PASS = "correct horse battery staple"
CREATED = "2026-01-01T00:00:00+00:00"


def _source_members(tmp_path: Path):
    src = tmp_path / "src"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_bytes(b"alpha line\n" * 1000)
    # > 1 MiB so the stream spans more than one encrypted frame
    (src / "sub" / "b.bin").write_bytes(bytes(range(256)) * 5000)
    return [("config/a.txt", src / "a.txt"), ("config/sub/b.bin", src / "sub" / "b.bin")]


def _write_real(tmp_path: Path, name="ontosage-20260101T000000Z.enc", passphrase=PASS) -> Path:
    out = tmp_path / "out"
    out.mkdir(exist_ok=True)
    path = out / name
    be.write_archive(
        path,
        passphrase,
        _source_members(tmp_path),
        building_id="bldg1",
        created=CREATED,
        skipped=[],
    )
    return path


def _entry(name: str, data: bytes) -> dict:
    return {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def _manual_archive(path: Path, files: dict, members, include_manifest=True) -> Path:
    """Write an archive whose manifest we control, to test the verification failures."""
    with open(path, "wb") as fh:
        with fmt.EncryptedWriter(fh, PASS) as enc:
            with tarfile.open(fileobj=enc, mode="w|gz") as tar:
                for name, data in files.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
                if include_manifest:
                    blob = json.dumps(
                        {
                            "format": rs.FORMAT_NAME,
                            "format_version": 1,
                            "building_id": "bldg1",
                            "created_utc": CREATED,
                            "members": members,
                            "skipped": [],
                        }
                    ).encode("utf-8")
                    info = tarfile.TarInfo("manifest.json")
                    info.size = len(blob)
                    tar.addfile(info, io.BytesIO(blob))
    return path


def _verify(path: Path, passphrase: str = PASS, dest: Path = None):
    dest = dest or path.parent / "verify-out"
    dest.mkdir(exist_ok=True)
    return rs.extract_and_verify(path, passphrase, dest)


# ---------- round trip and tamper detection ----------


def test_round_trip_restores_every_byte_and_lists_every_member(tmp_path):
    archive = _write_real(tmp_path)
    dest = tmp_path / "restored"
    dest.mkdir()
    manifest = rs.extract_and_verify(archive, PASS, dest)
    assert (dest / "config" / "a.txt").read_bytes() == b"alpha line\n" * 1000
    assert (dest / "config" / "sub" / "b.bin").read_bytes() == bytes(range(256)) * 5000
    names = {m["name"] for m in manifest["members"]}
    assert names == {"config/a.txt", "config/sub/b.bin"}
    assert manifest["building_id"] == "bldg1"


def test_flipped_ciphertext_byte_fails_authentication(tmp_path):
    archive = _write_real(tmp_path)
    data = bytearray(archive.read_bytes())
    data[len(data) // 2] ^= 0x01
    tampered = tmp_path / "tampered.enc"
    tampered.write_bytes(bytes(data))
    with pytest.raises(fmt.ArchiveAuthError):
        _verify(tampered)


def test_flipped_salt_byte_fails_authentication(tmp_path):
    archive = _write_real(tmp_path)
    data = bytearray(archive.read_bytes())
    data[len(fmt.MAGIC) + 1 + 3] ^= 0x10  # inside the salt
    tampered = tmp_path / "salt.enc"
    tampered.write_bytes(bytes(data))
    with pytest.raises(fmt.ArchiveAuthError):
        _verify(tampered)


def test_flipped_final_frame_flag_fails_authentication(tmp_path):
    archive = _write_real(tmp_path)
    data = bytearray(archive.read_bytes())
    data[fmt.HEADER_LEN] ^= 0x01  # the first frame's FLAG byte: 0 -> 1 changes the AAD
    tampered = tmp_path / "flag.enc"
    tampered.write_bytes(bytes(data))
    with pytest.raises(fmt.ArchiveAuthError):
        _verify(tampered)


def test_wrong_passphrase_fails(tmp_path):
    archive = _write_real(tmp_path)
    with pytest.raises(fmt.ArchiveAuthError):
        _verify(archive, passphrase="not the passphrase at all")


def test_truncated_archive_is_rejected(tmp_path):
    archive = _write_real(tmp_path)
    cut = tmp_path / "cut.enc"
    cut.write_bytes(archive.read_bytes()[:-100])
    with pytest.raises(fmt.ArchiveFormatError):
        _verify(cut)


def test_data_after_the_final_frame_is_rejected(tmp_path):
    archive = _write_real(tmp_path)
    padded = tmp_path / "padded.enc"
    padded.write_bytes(archive.read_bytes() + b"x")
    with pytest.raises(fmt.ArchiveFormatError):
        _verify(padded)


def test_a_file_that_is_not_an_archive_is_refused_by_magic(tmp_path):
    bogus = tmp_path / "bogus.enc"
    bogus.write_bytes(b"hello world, this is not an archive" * 4)
    with pytest.raises(fmt.ArchiveFormatError, match="magic"):
        _verify(bogus)


def test_passphrase_must_not_be_empty():
    with pytest.raises(ValueError):
        fmt.derive_key("", b"0" * fmt.SALT_LEN)


# ---------- manifest verification ----------


def test_manifest_sha_mismatch_fails(tmp_path):
    body = b"real content"
    archive = _manual_archive(
        tmp_path / "bad.enc",
        {"config/a.txt": body},
        members=[{"name": "config/a.txt", "size": len(body), "sha256": "0" * 64}],
    )
    with pytest.raises(rs.ManifestMismatch) as info:
        _verify(archive)
    assert any("sha256 mismatch: config/a.txt" in p for p in info.value.problems)


def test_member_missing_from_archive_fails(tmp_path):
    archive = _manual_archive(
        tmp_path / "missing.enc",
        {"config/a.txt": b"x"},
        members=[_entry("config/a.txt", b"x"), _entry("config/gone.txt", b"y")],
    )
    with pytest.raises(rs.ManifestMismatch) as info:
        _verify(archive)
    assert "missing member: config/gone.txt" in info.value.problems


def test_member_not_listed_in_manifest_fails(tmp_path):
    archive = _manual_archive(
        tmp_path / "unlisted.enc",
        {"config/a.txt": b"x", "config/extra.txt": b"y"},
        members=[_entry("config/a.txt", b"x")],
    )
    with pytest.raises(rs.ManifestMismatch) as info:
        _verify(archive)
    assert "unlisted member: config/extra.txt" in info.value.problems


def test_archive_without_manifest_fails(tmp_path):
    archive = _manual_archive(
        tmp_path / "nomanifest.enc", {"a.txt": b"x"}, members=[], include_manifest=False
    )
    with pytest.raises(fmt.ArchiveFormatError, match="manifest"):
        _verify(archive)


def test_unsafe_member_names_are_refused():
    for bad in ("../escape.txt", "/etc/passwd", "C:/Windows/x", "a\\b", ""):
        with pytest.raises(fmt.ArchiveFormatError):
            rs.safe_member_path(bad)
    assert str(rs.safe_member_path("config/sub/b.bin")) == "config/sub/b.bin"


# ---------- CLI behaviour ----------


def test_cli_verify_only_and_restore(tmp_path, monkeypatch):
    archive = _write_real(tmp_path)
    monkeypatch.setattr(sec, "get_passphrase", lambda **_: PASS)
    assert rs.main([str(archive), "--verify-only"]) == 0

    dest = tmp_path / "dest"
    assert rs.main([str(archive), "--dest", str(dest)]) == 0
    assert (dest / "config" / "a.txt").exists()
    # a second restore into the now non-empty destination is refused
    assert rs.main([str(archive), "--dest", str(dest)]) == 5


def test_cli_maps_wrong_passphrase_to_exit_2(tmp_path, monkeypatch):
    archive = _write_real(tmp_path)
    monkeypatch.setattr(sec, "get_passphrase", lambda **_: "wrong passphrase value")
    assert rs.main([str(archive), "--verify-only"]) == 2


def test_cli_maps_manifest_mismatch_to_exit_4(tmp_path, monkeypatch):
    archive = _manual_archive(
        tmp_path / "m.enc",
        {"config/a.txt": b"x"},
        members=[{"name": "config/a.txt", "size": 1, "sha256": "f" * 64}],
    )
    monkeypatch.setattr(sec, "get_passphrase", lambda **_: PASS)
    assert rs.main([str(archive), "--verify-only"]) == 4


# ---------- backup run: partial sources, retention, planning ----------


def test_run_writes_one_archive_and_records_skipped_sources(tmp_path, monkeypatch):
    def unavailable(_out):
        raise be.SourceSkipped("docker CLI not found on PATH")

    items = [
        be.Item("file", "config/a.txt", "a", path=_source_members(tmp_path)[0][1]),
        be.Item("dump", "db/pg.dump", "pg", produce=unavailable),
    ]
    monkeypatch.setattr(be, "build_plan", lambda *a, **k: items)
    out_dir = tmp_path / "backups"
    conn = be.Conn(
        building_id="bldg1",
        mysql_host="mysql",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="x",
        mysql_database="sensordb",
        pg_user="u",
        pg_password="p",
        pg_database="d",
        pg_container="postgres-user-data",
        graph_url="http://graphdb:7200",
        graph_repo="bldg1",
        graph_user="admin",
        graph_password="x",
    )
    code = be.run(
        conn=conn,
        repo_root=tmp_path,
        out_dir=out_dir,
        include_sensor_data=False,
        keep=14,
        passphrase_fn=lambda: PASS,
    )
    assert code == 3  # written, but a source was skipped
    archives = list(out_dir.glob("ontosage-*.enc"))
    assert len(archives) == 1
    assert not list(out_dir.glob("*.partial"))
    assert not [p for p in out_dir.iterdir() if p.name.startswith(".staging-")]
    manifest = rs.extract_and_verify(archives[0], PASS, tmp_path / "v")
    assert manifest["skipped"][0]["source"] == "pg"


def _run_with_items(tmp_path, items, monkeypatch, out_dir):
    monkeypatch.setattr(be, "build_plan", lambda *a, **k: items)
    conn = be.Conn(
        building_id="bldg1",
        mysql_host="mysql",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="x",
        mysql_database="sensordb",
        pg_user="u",
        pg_password="p",
        pg_database="d",
        pg_container="c",
        graph_url="http://graphdb:7200",
        graph_repo="bldg1",
        graph_user="admin",
        graph_password="x",
    )
    return be.run(
        conn=conn,
        repo_root=tmp_path,
        out_dir=out_dir,
        include_sensor_data=False,
        keep=0,
        passphrase_fn=lambda: PASS,
    )


def test_an_os_error_in_one_dump_is_recorded_and_the_others_still_run(tmp_path, monkeypatch):
    def times_out(_out):
        raise TimeoutError("pg_dump took too long")

    src = _source_members(tmp_path)[0][1]
    items = [
        be.Item("dump", "db/pg.dump", "pg", produce=times_out),
        be.Item("file", "config/a.txt", "a", path=src),
    ]
    out_dir = tmp_path / "backups"
    assert _run_with_items(tmp_path, items, monkeypatch, out_dir) == 3
    archive = next(out_dir.glob("ontosage-*.enc"))
    manifest = rs.extract_and_verify(archive, PASS, tmp_path / "v")
    assert manifest["skipped"][0]["reason"].startswith("TimeoutError")
    assert [m["name"] for m in manifest["members"]] == ["config/a.txt"]


def test_a_required_source_failure_writes_no_archive(tmp_path, monkeypatch):
    def fails(_out):
        raise be.SourceSkipped("mysqldump exit 2")

    items = [be.Item("dump", "db/sensordb.sql", "sensor", produce=fails, required=True)]
    out_dir = tmp_path / "backups"
    assert _run_with_items(tmp_path, items, monkeypatch, out_dir) == 1
    assert not out_dir.exists() or not list(out_dir.glob("ontosage-*.enc"))


def test_prune_keeps_newest_and_touches_only_matching_archives(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for day in range(1, 6):
        (out / f"ontosage-2026010{day}T000000Z.enc").write_bytes(b"x")
    (out / "notes.txt").write_text("keep me")
    (out / "ontosage-2026010XT.enc.partial").write_bytes(b"in progress")
    deleted = be.prune(out, keep=2)
    assert len(deleted) == 3
    remaining = sorted(p.name for p in out.iterdir())
    assert remaining == [
        "notes.txt",
        "ontosage-20260104T000000Z.enc",
        "ontosage-20260105T000000Z.enc",
        "ontosage-2026010XT.enc.partial",
    ]


def test_prune_with_keep_zero_deletes_nothing(tmp_path):
    (tmp_path / "ontosage-20260101T000000Z.enc").write_bytes(b"x")
    assert be.prune(tmp_path, keep=0) == []
    assert (tmp_path / "ontosage-20260101T000000Z.enc").exists()


def test_plan_excludes_sensor_store_unless_asked(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "bldg1_x.ttl").write_text("@prefix x: <urn:x> .")
    (tmp_path / ".env1").write_text("SECRET=1")
    conn = be.Conn(
        building_id="bldg1",
        mysql_host="host.docker.internal",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="x",
        mysql_database="sensordb",
        pg_user="u",
        pg_password="p",
        pg_database="d",
        pg_container="postgres-user-data",
        graph_url="http://graphdb:7200",
        graph_repo="bldg1",
        graph_user="admin",
        graph_password="x",
    )
    routine = be.build_plan(conn, tmp_path, False, tmp_path / "volumes")
    arcs = [i.arcname for i in routine]
    assert "config/input" in arcs and "config/env" in arcs
    assert "db/sensordb.sql" not in arcs

    full = be.build_plan(conn, tmp_path, True, tmp_path / "volumes")
    sensor = [i for i in full if i.arcname == "db/sensordb.sql"]
    assert len(sensor) == 1 and sensor[0].required is True


def test_dry_run_names_the_exclusion_and_writes_nothing(tmp_path, capsys):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "f.ttl").write_text("x")
    conn = be.Conn(
        building_id="bldg1",
        mysql_host="mysql",
        mysql_port=3306,
        mysql_user="root",
        mysql_password="x",
        mysql_database="sensordb",
        pg_user="u",
        pg_password="p",
        pg_database="d",
        pg_container="c",
        graph_url="http://graphdb:7200",
        graph_repo="bldg1",
        graph_user="admin",
        graph_password="x",
    )
    items = be.build_plan(conn, tmp_path, False, tmp_path / "volumes")
    be.print_dry_run(items, tmp_path / "out" / "ontosage-x.enc", False)
    text = capsys.readouterr().out
    assert "DRY RUN" in text and "EXCLUDED" in text
    assert not (tmp_path / "out").exists()


def test_graph_export_url_maps_docker_names_for_host_side_access():
    conn = be.Conn(
        building_id="bldg1",
        mysql_host="x",
        mysql_port=3306,
        mysql_user="u",
        mysql_password="p",
        mysql_database="d",
        pg_user="u",
        pg_password="p",
        pg_database="d",
        pg_container="c",
        graph_url="http://graphdb:7200",
        graph_repo="bldg1",
        graph_user="admin",
        graph_password="p",
    )
    assert be.graph_export_url(conn) == (
        "http://127.0.0.1:7200/repositories/bldg1/statements?infer=false"
    )
    assert be.host_for_host_tools("localhost") == "localhost"
