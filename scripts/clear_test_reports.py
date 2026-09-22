# -*- coding: utf-8 -*-
"""Remove the tickets that verification runs file, and only those (dry run unless --apply).

Every regression-probe, demo and rehearsal run files a maintenance report ("The toilet on floor 2 is
leaking.") from a test login, and a fresh push adds dozens more. Left in `user_reports` they show up in
answers ("4 places with repeat reports"), so a supervisor sees the test suite's own tickets.

SCOPE, ON PURPOSE NARROW. A row is removed only if it was created since ``--since`` AND was reported by
one of ``--reporters`` (the test logins). System-generated rows (the rules engine's alerts) and anything
filed by another login are never touched. The rows are written to a CSV backup BEFORE deletion.

    python scripts/clear_test_reports.py --since 2026-09-19 --reporters facility01,admin@ontosage
    python scripts/clear_test_reports.py --since 2026-09-19 --reporters facility01,admin@ontosage --apply

Reaches Postgres through the compose container (no host driver needed): ``docker exec <container> psql``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List

REPO = Path(__file__).resolve().parent.parent
_SAFE = re.compile(r"^[A-Za-z0-9_.@\-]+$")


def _psql(container: str, user: str, db: str, sql: str, csv_out: bool = False) -> str:
    if csv_out:
        cmd = ["docker", "exec", container, "psql", "-U", user, "-d", db, "-c",
               f"\\copy ({sql}) TO STDOUT WITH CSV HEADER"]
    else:
        cmd = ["docker", "exec", container, "psql", "-U", user, "-d", db, "-At", "-c", sql]
    out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or "psql failed")
    return out.stdout


def _container_env(container: str, key: str) -> str:
    out = subprocess.run(
        ["docker", "exec", container, "printenv", key], capture_output=True, text=True, encoding="utf-8"
    )
    return out.stdout.strip()


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="YYYY-MM-DD; only rows created on or after this")
    ap.add_argument("--reporters", required=True, help="comma-separated test logins")
    ap.add_argument("--container", default="postgres-user-data")
    ap.add_argument("--backup-dir", default=str(REPO / "scripts" / "outputs"))
    ap.add_argument("--apply", action="store_true", help="delete (default is a dry run)")
    args = ap.parse_args(argv)

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.since):
        print("--since must be YYYY-MM-DD", file=sys.stderr)
        return 2
    reporters = [r.strip() for r in args.reporters.split(",") if r.strip()]
    if not reporters or not all(_SAFE.match(r) for r in reporters):
        print("--reporters holds an unsafe or empty login", file=sys.stderr)
        return 2

    user = _container_env(args.container, "POSTGRES_USER")
    db = _container_env(args.container, "POSTGRES_DB")
    if not user or not db:
        print(f"could not read the database role from container {args.container}", file=sys.stderr)
        return 2
    quoted = ",".join("'" + r + "'" for r in reporters)
    where = f"created_at >= '{args.since}' AND reporter_id IN ({quoted})"

    total = int(_psql(args.container, user, db, "SELECT count(*) FROM user_reports").strip() or 0)
    n = int(_psql(args.container, user, db, f"SELECT count(*) FROM user_reports WHERE {where}").strip() or 0)
    print(f"user_reports: {total} rows; {n} match (since {args.since}, reporters {reporters})")
    if n == 0:
        return 0
    sample = _psql(
        args.container, user, db,
        f"SELECT id, category, left(coalesce(description,title,''),60) FROM user_reports WHERE {where} "
        "ORDER BY created_at LIMIT 8",
    )
    print(sample.rstrip())

    backup = Path(args.backup_dir) / f"user_reports_backup_{datetime.now():%Y%m%d_%H%M%S}.csv"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_text(
        _psql(args.container, user, db, f"SELECT * FROM user_reports WHERE {where}", csv_out=True),
        encoding="utf-8",
    )
    print(f"backup: {backup}")
    if not args.apply:
        print("dry run: nothing deleted (add --apply)")
        return 0
    _psql(args.container, user, db, f"DELETE FROM user_reports WHERE {where}")
    left = _psql(args.container, user, db, "SELECT count(*) FROM user_reports").strip()
    print(f"deleted {n}; {left} rows remain")
    return 0


if __name__ == "__main__":
    sys.exit(main())
