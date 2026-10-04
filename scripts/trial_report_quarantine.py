#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""H8 (QA-trial plan, 2026-10-04): separate real tester reports from machine-written ones.

`user_reports` holds rows the rules engine files on its own (a sensor threshold breach,
for example) alongside rows a real person typed during a conversation. An admin reviewing
the trial cannot tell at a glance which rows a human actually left, and testers were told
their reports are real -- so the split needs to be visible, not assumed.

No DDL change: the split is one query -- `reporter_id <> 'rules_engine'` and (optionally)
`created_at >= <trial start>`. This script just runs it and prints the human-filed rows.

Usage:
    python scripts/trial_report_quarantine.py                          # all human rows
    python scripts/trial_report_quarantine.py --since 2026-10-02       # from the trial start
    python scripts/trial_report_quarantine.py --count-only             # just the totals

Connects to the user-data Postgres directly (the published host port, not the Docker-
internal hostname, since this is meant to be run from the host as an operational check).
Reads connection details from the SAME env vars shared/config.py's Settings defines
(POSTGRES_USER_USER/PASSWORD/DB), falling back to their documented defaults, and always
connects via 127.0.0.1:5433 (the host-published port docker-compose.yml binds) rather than
the container-internal hostname.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import date, datetime
from typing import Optional

import asyncpg

MACHINE_REPORTER = "rules_engine"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


async def _connect() -> asyncpg.Connection:
    return await asyncpg.connect(
        host="127.0.0.1",
        port=5433,
        user=_env("POSTGRES_USER_USER", "ontobot"),
        password=_env("POSTGRES_USER_PASSWORD", "ontobot_secret"),
        database=_env("POSTGRES_USER_DB", "ontobot"),
        timeout=10,
    )


async def quarantine(since: Optional[date], count_only: bool) -> int:
    conn = await _connect()
    try:
        total = await conn.fetchval("SELECT COUNT(*) FROM user_reports")
        machine = await conn.fetchval(
            "SELECT COUNT(*) FROM user_reports WHERE reporter_id = $1", MACHINE_REPORTER
        )
        where = "reporter_id <> $1"
        args = [MACHINE_REPORTER]
        if since is not None:
            where += " AND created_at >= $2"
            args.append(datetime(since.year, since.month, since.day))
        human_count = await conn.fetchval(f"SELECT COUNT(*) FROM user_reports WHERE {where}", *args)
        print(
            f"user_reports: {total} total, {machine} machine-written, {human_count} human-filed"
            + (f" since {since.isoformat()}" if since else "")
        )
        if count_only:
            return 0

        rows = await conn.fetch(
            f"""SELECT id, created_at, reporter_id, category, priority, status, title
                FROM user_reports WHERE {where} ORDER BY created_at DESC""",
            *args,
        )
        print()
        for r in rows:
            print(
                f"  {r['id']:>6}  {r['created_at']}  {r['reporter_id']:<20} "
                f"{r['category']:<15} {r['priority']:<8} {r['status']:<12} {r['title'][:50]}"
            )
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--since", type=str, default=None, help="Only rows created on/after this date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--count-only", action="store_true", help="Print only the totals, not the row list"
    )
    args = parser.parse_args()
    since = date.fromisoformat(args.since) if args.since else None
    return asyncio.run(quarantine(since, args.count_only))


if __name__ == "__main__":
    sys.exit(main())
