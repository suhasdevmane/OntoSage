#!/usr/bin/env python
"""Encrypted local backup of one building's state: ONE archive per run.

Output: ``<out-dir>/ontosage-<UTC timestamp>.enc`` (AES-256-GCM, scrypt key; see
_backup_format.py). The archive holds a gzip tar with a ``manifest.json`` as its last
member, listing every member with its size and sha256. restore_encrypted.py verifies both.

What is included (routine run):
  config/<folder>   the active input/ folder, or the parked <BUILDING_ID>/ folder
  config/env        .env, or .env<N> while parked (secrets: the archive is encrypted)
  graph             GraphDB repository export, explicit statements only (needs the service up;
                    skipped and recorded in the manifest otherwise, the TTL files still cover it)
  db/postgres-user-data.dump   pg_dump -Fc of the user-data DB (users, RBAC, turn memory,
                    reports) via `docker exec` into the postgres-user-data container
  artifacts/        volumes/<BUILDING_ID>/artifacts when present

What is excluded, and why:
  sensor data (MySQL sensordb, ~9 GB per the owner)   opt-in: --include-sensor-data
  redis, Qdrant vectors, Ollama models                rebuildable (cache / reindex / re-pull)
  open-webui and mongo chat transcripts               NOT excluded by design, but NOT
                    in this script's scope yet; see docs/RUNBOOK.md "Costs of each operation"

Exit codes: 0 complete · 1 unexpected failure · 2 no passphrase / bad arguments ·
3 archive written but one or more included sources were skipped (see manifest).

Examples::

    python scripts/backup_encrypted.py --dry-run
    python scripts/backup_encrypted.py                       # routine run
    python scripts/backup_encrypted.py --include-sensor-data # adds the MySQL sensor store
"""

import argparse
import base64
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _backup_format import CHUNK_SIZE  # noqa: E402
from _backup_format import write_archive as _write_format_archive  # noqa: E402

FORMAT_NAME = "ontosage-encrypted-backup"
FORMAT_VERSION = 1
ARCHIVE_PREFIX = "ontosage-"
ARCHIVE_SUFFIX = ".enc"
# Archives written by the orchestrator's automatic backup. Routine and automatic archives may
# share a folder, so neither side may delete the other's files: this script's retention skips
# this prefix, and the orchestrator's retention touches nothing else.
AUTO_ARCHIVE_PREFIX = "ontosage-auto-"
PG_CONTAINER_DEFAULT = "postgres-user-data"
# Compose service names that resolve only inside the docker network. Host-side tools
# (mysqldump, urllib) cannot resolve them, so they are mapped to loopback. Container-side
# tools (docker exec) never see these names and are not affected.
DOCKER_ONLY_HOSTS = {
    "mysql",
    "mysql-bldg1",
    "host.docker.internal",
    "graphdb",
    "postgres-user-data",
    "postgres",
}
EXCLUDED_BY_DESIGN = [
    ("sensor data (MySQL sensordb, ~9 GB per owner)", "opt-in: --include-sensor-data"),
    ("redis (cache + sessions)", "rebuildable; ~385 MB on disk, not needed for recovery"),
    ("qdrant (vector index)", "rebuildable from documents/floor plans via reindex"),
    ("ollama (model weights)", "re-pullable; ~23 GB on disk"),
    ("open-webui / mongo (chat transcripts)", "not in this script's scope yet; NOT rebuildable"),
    ("graphdb volume (raw store)", "covered by the explicit-statement export"),
]


@dataclass
class Conn:
    """Connection settings, read from shared.config.settings at run time."""

    building_id: str
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    pg_user: str
    pg_password: str
    pg_database: str
    pg_container: str
    graph_url: str
    graph_repo: str
    graph_user: str
    graph_password: str


def load_conn() -> Conn:
    """Read every connection value from shared.config.settings (nothing hardcoded)."""
    # STRICT_SECRETS makes shared.config refuse to load while any secret is still a default.
    # That guard protects a server from booting with placeholders; this script serves nothing
    # and only reads connection values, so a parked checkout with no .env must still back up.
    # setdefault: a real environment or .env value still wins.
    os.environ.setdefault("STRICT_SECRETS", "false")
    from shared.config import settings as s

    return Conn(
        building_id=s.BUILDING_ID,
        mysql_host=s.MYSQL_HOST,
        mysql_port=int(s.MYSQL_PORT),
        mysql_user=s.MYSQL_USER,
        mysql_password=s.MYSQL_PASSWORD,
        mysql_database=s.MYSQL_DATABASE,
        pg_user=s.POSTGRES_USER_USER,
        pg_password=s.POSTGRES_USER_PASSWORD,
        pg_database=s.POSTGRES_USER_DB,
        pg_container=os.environ.get("BACKUP_PG_CONTAINER", PG_CONTAINER_DEFAULT),
        graph_url=s.GRAPHDB_URL,
        graph_repo=s.GRAPHDB_REPOSITORY,
        graph_user=s.GRAPHDB_USER,
        graph_password=s.GRAPHDB_PASSWORD,
    )


def host_for_host_tools(host: str) -> str:
    """Map a docker-network service name to loopback for tools run on the Windows host."""
    return "127.0.0.1" if host in DOCKER_ONLY_HOSTS else host


def graph_export_url(conn: Conn) -> str:
    """Explicit-statement N-Quads export URL, with the host mapped for host-side access."""
    parts = urllib.parse.urlsplit(conn.graph_url)
    host = host_for_host_tools(parts.hostname or "127.0.0.1")
    netloc = host + (f":{parts.port}" if parts.port else "")
    base = urllib.parse.urlunsplit((parts.scheme or "http", netloc, parts.path, "", ""))
    repo = urllib.parse.quote(conn.graph_repo, safe="")
    return f"{base.rstrip('/')}/repositories/{repo}/statements?infer=false"


class SourceSkipped(Exception):
    """An included source could not be produced; recorded in the manifest, not fatal."""


@dataclass
class Item:
    """One planned archive member or group of members."""

    kind: str  # "file" | "tree" | "dump"
    arcname: str
    label: str
    path: Optional[Path] = None
    produce: Optional[Callable[[Path], None]] = None
    est_bytes: Optional[int] = None
    est_note: str = ""
    required: bool = False


def _tree_files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def _dir_size(root: Path) -> int:
    return sum(p.stat().st_size for p in _tree_files(root))


def _mysql_dump(conn: Conn) -> Callable[[Path], None]:
    def produce(out: Path) -> None:
        tool = shutil.which("mysqldump")
        if not tool:
            raise SourceSkipped("mysqldump not found on PATH")
        if not re.fullmatch(r"[A-Za-z0-9_]+", conn.mysql_database):
            raise SourceSkipped("MYSQL_DATABASE contains characters this script will not pass")
        cmd = [
            tool,
            "-h",
            host_for_host_tools(conn.mysql_host),
            "-P",
            str(conn.mysql_port),
            "-u",
            conn.mysql_user,
            "--single-transaction",
            "--routines",
            "--triggers",
            "--result-file",
            str(out),
            conn.mysql_database,
        ]
        env = {**os.environ, "MYSQL_PWD": conn.mysql_password}
        res = subprocess.run(cmd, env=env, capture_output=True, timeout=6 * 3600)
        if res.returncode != 0:
            raise SourceSkipped(f"mysqldump exit {res.returncode}")

    return produce


def _pg_dump(conn: Conn) -> Callable[[Path], None]:
    def produce(out: Path) -> None:
        cmd = [
            "docker",
            "exec",
            "-e",
            "PGPASSWORD",  # value comes from the environment, never the command line
            conn.pg_container,
            "pg_dump",
            "-U",
            conn.pg_user,
            "-d",
            conn.pg_database,
            "-Fc",
            "--no-owner",
        ]
        env = {**os.environ, "PGPASSWORD": conn.pg_password}
        try:
            with open(out, "wb") as fh:
                res = subprocess.run(cmd, stdout=fh, stderr=subprocess.PIPE, env=env, timeout=3600)
        except FileNotFoundError as exc:
            raise SourceSkipped("docker CLI not found on PATH") from exc
        if res.returncode != 0:
            raise SourceSkipped(
                f"pg_dump via docker exec {conn.pg_container!r} exit {res.returncode}"
            )

    return produce


def _graph_export(conn: Conn) -> Callable[[Path], None]:
    def produce(out: Path) -> None:
        url = graph_export_url(conn)
        token = base64.b64encode(f"{conn.graph_user}:{conn.graph_password}".encode()).decode()
        req = urllib.request.Request(
            url, headers={"Accept": "application/n-quads", "Authorization": f"Basic {token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=600) as resp, open(out, "wb") as fh:
                shutil.copyfileobj(resp, fh, CHUNK_SIZE)
        except OSError as exc:
            raise SourceSkipped(f"GraphDB export unreachable ({type(exc).__name__})") from exc

    return produce


def build_plan(
    conn: Conn, repo_root: Path, include_sensor_data: bool, volumes_root: Path
) -> List[Item]:
    """Return the ordered list of items this run would include. No I/O beyond stat calls."""
    items: List[Item] = []

    config_dir = repo_root / "input"
    if not config_dir.is_dir():
        config_dir = repo_root / conn.building_id
    if config_dir.is_dir():
        items.append(
            Item("tree", f"config/{config_dir.name}", f"config ({config_dir.name}/)", config_dir)
        )

    suffix = re.sub(r"^\D+", "", conn.building_id)
    for env_name in (".env", f".env{suffix}"):
        env_path = repo_root / env_name
        if env_path.is_file():
            items.append(Item("file", "config/env", f"env file ({env_name})", env_path))
            break

    items.append(
        Item(
            "dump",
            "graph/explicit-statements.nq",
            "GraphDB explicit-statement export",
            produce=_graph_export(conn),
            est_note="needs the GraphDB service",
        )
    )
    pg_volume = volumes_root / conn.building_id / "postgres-user-data"
    pg_est = _dir_size(pg_volume) if pg_volume.is_dir() else None
    items.append(
        Item(
            "dump",
            "db/postgres-user-data.dump",
            "Postgres user-data (pg_dump -Fc)",
            produce=_pg_dump(conn),
            est_bytes=pg_est,
            est_note="upper bound: volume size on disk",
            required=False,
        )
    )

    artifacts = volumes_root / conn.building_id / "artifacts"
    if artifacts.is_dir():
        items.append(Item("tree", "artifacts", "volumes artifacts/", artifacts))

    if include_sensor_data:
        items.append(
            Item(
                "dump",
                "db/sensordb.sql",
                f"MySQL {conn.mysql_database} (sensor store)",
                produce=_mysql_dump(conn),
                est_note="unmeasured here; owner reports ~9 GB",
                required=True,
            )
        )
    return items


def _item_size(item: Item) -> Optional[int]:
    if item.kind == "file":
        return item.path.stat().st_size
    if item.kind == "tree":
        return _dir_size(item.path)
    return item.est_bytes


def print_dry_run(items: List[Item], out_path: Path, include_sensor_data: bool) -> None:
    """Print what a run would include and the sizes measured without touching the services."""
    print(f"DRY RUN: nothing will be written. Output would be: {out_path}")
    total = 0
    unmeasured = 0
    for item in items:
        size = _item_size(item)
        if size is None:
            unmeasured += 1
            size_txt = "unmeasured"
        else:
            total += size
            size_txt = _fmt(size)
        count = ""
        if item.kind == "tree":
            count = f" [{len(_tree_files(item.path))} files]"
        note = f" ({item.est_note})" if item.est_note else ""
        print(f"  + {item.arcname:<32} {item.label}{count}: {size_txt}{note}")
    if not include_sensor_data:
        print("  - sensor data (MySQL sensordb): EXCLUDED, pass --include-sensor-data to add it")
    for name, reason in EXCLUDED_BY_DESIGN:
        if "sensor data" in name and not include_sensor_data:
            continue
        print(f"  - {name}: {reason}")
    print(
        f"Measured raw total: {_fmt(total)} before gzip and encryption "
        f"({unmeasured} item(s) unmeasured; the compressed size is not measured here)."
    )


def _fmt(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} GB"


def prune(out_dir: Path, keep: int) -> List[Path]:
    """Delete the oldest routine ontosage-*.enc archives so that only `keep` remain.

    Automatic archives (AUTO_ARCHIVE_PREFIX) are never candidates here; they have their own
    retention in the orchestrator. Returns the deletions.
    """
    if keep <= 0:
        return []
    archives = sorted(
        p
        for p in out_dir.glob(f"{ARCHIVE_PREFIX}*{ARCHIVE_SUFFIX}")
        if not p.name.startswith(AUTO_ARCHIVE_PREFIX)
    )
    doomed = archives[:-keep] if len(archives) > keep else []
    for path in doomed:
        path.unlink()
    return doomed


def write_archive(
    out_path: Path,
    passphrase: str,
    members: List[Tuple[str, Path]],
    *,
    building_id: str,
    created: str,
    skipped: List[dict],
) -> dict:
    """Stream members into an encrypted archive; returns the manifest that was written last."""
    header = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "building_id": building_id,
        "created_utc": created,
        "skipped": skipped,
        "excluded_by_design": [name for name, _ in EXCLUDED_BY_DESIGN],
    }
    return _write_format_archive(out_path, passphrase, members, header)


def run(
    *,
    conn: Conn,
    repo_root: Path,
    out_dir: Path,
    include_sensor_data: bool,
    keep: int,
    passphrase_fn: Callable[[], str],
    now: Optional[dt.datetime] = None,
) -> int:
    """Perform one real backup run. Returns the process exit code."""
    now = now or dt.datetime.now(dt.timezone.utc)
    volumes_root = repo_root / "volumes"
    items = build_plan(conn, repo_root, include_sensor_data, volumes_root)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"

    try:
        passphrase = passphrase_fn()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=str(out_dir)))
    skipped: List[dict] = []
    members: List[Tuple[str, Path]] = []
    try:
        for item in items:
            if item.kind == "file":
                members.append((item.arcname, item.path))
            elif item.kind == "tree":
                for f in _tree_files(item.path):
                    rel = f.relative_to(item.path).as_posix()
                    members.append((f"{item.arcname}/{rel}", f))
            else:
                target = staging / Path(item.arcname).name
                try:
                    print(f"  dumping {item.label} ...", flush=True)
                    item.produce(target)
                    members.append((item.arcname, target))
                except Exception as exc:  # a timeout or OS error must not abort the others
                    reason = (
                        str(exc)
                        if isinstance(exc, SourceSkipped)
                        else (f"{type(exc).__name__}: {exc}")
                    )
                    if item.required:
                        print(f"error: required source failed: {item.label}: {reason}")
                        return 1
                    skipped.append({"source": item.label, "reason": reason})
                    print(f"  SKIPPED {item.label}: {reason}")
        write_archive(
            out_path,
            passphrase,
            members,
            building_id=conn.building_id,
            created=now.isoformat(),
            skipped=skipped,
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    deleted = prune(out_dir, keep)
    size = out_path.stat().st_size
    print(f"Wrote {out_path} ({_fmt(size)}, {len(members)} members).")
    if deleted:
        print(f"Pruned {len(deleted)} old archive(s); keeping the newest {keep}.")
    if skipped:
        print(f"WARNING: {len(skipped)} source(s) skipped; see manifest.json in the archive.")
        return 3
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Encrypted backup of one building's state.")
    parser.add_argument("--dry-run", action="store_true", help="list and size; write nothing")
    parser.add_argument(
        "--out-dir",
        default=os.environ.get("ONTOSAGE_BACKUP_DIR", str(Path.home() / "OntoSage-backups")),
        help="archive directory (default: %%ONTOSAGE_BACKUP_DIR%% or ~/OntoSage-backups)",
    )
    parser.add_argument(
        "--include-sensor-data",
        action="store_true",
        help="also dump the MySQL sensor store (large; opt-in)",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="keep the newest N ontosage-*.enc archives; 0 keeps all (default 14)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO_ROOT,
        help="checkout whose input/ or bldg<N>/, .env and volumes/ are backed up "
        "(default: this checkout; use it to measure another checkout with --dry-run)",
    )
    args = parser.parse_args(argv)

    conn = load_conn()
    out_dir = Path(args.out_dir)
    repo_root = args.repo_root.resolve()
    if args.dry_run:
        items = build_plan(conn, repo_root, args.include_sensor_data, repo_root / "volumes")
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = out_dir / f"{ARCHIVE_PREFIX}{stamp}{ARCHIVE_SUFFIX}"
        print_dry_run(items, out_path, args.include_sensor_data)
        return 0

    from _backup_secret import get_passphrase

    return run(
        conn=conn,
        repo_root=repo_root,
        out_dir=out_dir,
        include_sensor_data=args.include_sensor_data,
        keep=args.keep,
        passphrase_fn=lambda: get_passphrase(creating=True),
    )


if __name__ == "__main__":
    sys.exit(main())
