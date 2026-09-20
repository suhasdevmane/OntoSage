# -*- coding: utf-8 -*-
"""The 'closed' column of a recurrence answer compared status in lower case; it is stored upper.

``user_reports.status`` holds 'OPEN', 'ACKNOWLEDGED', 'IN_PROGRESS', 'RESOLVED', 'CLOSED',
'REJECTED' (``VALID_STATUSES``, and the INSERT writes 'OPEN'). ``recurring_reports`` counted
``status IN ('resolved', 'closed')``, which matches nothing, so every recurrence answer printed
"closed: 0" beside places whose reports had in fact been resolved.

The database is replaced by a connection that records the SQL and evaluates the comparison the way
PostgreSQL would, so the test fails on the old text and passes on the new.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

import pytest

from orchestrator.services.report_intake_service import VALID_STATUSES, ReportIntakeService

pytestmark = pytest.mark.unit


class _Conn:
    def __init__(self) -> None:
        self.sql = ""

    async def fetch(self, sql: str, *args: Any) -> List[Dict[str, Any]]:
        self.sql = sql
        return []


class _Pool:
    def __init__(self, conn: _Conn) -> None:
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False

        return _Ctx()


def _closed_predicate() -> str:
    conn = _Conn()
    service = ReportIntakeService(postgres_manager=type("PG", (), {"pool": _Pool(conn)})())
    asyncio.run(service.recurring_reports("bldg1"))
    match = re.search(r"FILTER \(WHERE (.+?)\) AS closed", conn.sql)
    assert match, conn.sql
    return match.group(1)


def _evaluates_true(predicate: str, stored: str) -> bool:
    """The predicate as PostgreSQL would read it, for one stored status value."""
    # UPPER(status) IN ('A', 'B')  /  status IN ('a', 'b')
    upper = "UPPER(status)" in predicate
    members = re.findall(r"'([^']*)'", predicate)
    value = stored.upper() if upper else stored
    return value in members


@pytest.mark.parametrize("stored", ["RESOLVED", "CLOSED"])
def test_a_resolved_or_closed_report_is_counted_as_closed(stored):
    assert stored in VALID_STATUSES
    assert _evaluates_true(_closed_predicate(), stored)


@pytest.mark.parametrize("stored", ["OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "REJECTED"])
def test_a_report_still_open_is_not_counted_as_closed(stored):
    assert not _evaluates_true(_closed_predicate(), stored)


def test_the_comparison_does_not_depend_on_how_a_writer_cased_it():
    assert _evaluates_true(_closed_predicate(), "resolved")
