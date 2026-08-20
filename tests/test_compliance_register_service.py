# -*- coding: utf-8 -*-
"""V5-T26: compliance-register QA lane — classification, items, handlers, honesty."""

import asyncio
from datetime import datetime

import pytest

from orchestrator.services.compliance_register_service import (
    ComplianceRegisterService,
    _horizon_days,
    classify_register_question,
    match_item,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 8, 17, 10, 0, 0)
NS = "http://ontosage.org/testbldg#"


def test_kind_classification():
    assert classify_register_question("Which compliance checks are overdue?") == "overdue_list"
    assert classify_register_question("Anything past due on the register?") == "overdue_list"
    assert classify_register_question("When was the fire alarm last tested?") == "last_done"
    assert classify_register_question("legionella flush history") == "last_done"
    assert classify_register_question("What inspections are due this month?") == "due_soon"
    assert classify_register_question("what's coming up this week?") == "due_soon"


def test_item_matching():
    assert match_item("when was the fire alarm last tested") == "fire alarm"
    assert match_item("PAT testing record") == "PAT"
    assert match_item("last legionella outlet flush") == "legionella"
    assert match_item("LOLER examination for the lift") == "lift"
    assert match_item("when was the widget last tested") is None


def test_horizon_days():
    assert _horizon_days("due in the next 14 days") == 14
    assert _horizon_days("what's due this month?") == 31
    assert _horizon_days("due this quarter") == 92
    assert _horizon_days("what is due soon?") == 30


class _FakeSparql:
    """Canned bindings keyed on query content; records every query."""

    def __init__(self, rows=None, count=0, done_rows=None, due_rows=None):
        self.rows = rows or []
        self.count = count
        self.done_rows = done_rows if done_rows is not None else []
        self.due_rows = due_rows if due_rows is not None else []
        self.queries = []

    async def __call__(self, query):
        self.queries.append(query)
        if "COUNT(?c)" in query:
            bindings = [{"n": {"value": str(self.count)}}]
        elif "completedDate> ?done" in query:
            bindings = self.done_rows
        elif "ORDER BY ?due LIMIT 1" in query:
            bindings = self.due_rows
        else:
            bindings = self.rows
        return {"results": {"bindings": bindings}}


def _row(local, due, role="facilities team", label=None):
    b = {
        "c": {"value": f"{NS}{local}"},
        "due": {"value": due},
        "role": {"value": role},
    }
    if label:
        b["label"] = {"value": label}
    return b


def _svc(fake):
    return ComplianceRegisterService(fake, NS)


def test_overdue_lists_items_with_dates_and_roles():
    fake = _FakeSparql(
        rows=[
            _row("check_fire_door_1", "2026-07-01T00:00:00", label="Fire door inspection"),
            _row("check_pat_1", "2026-06-15T00:00:00", label="PAT testing"),
        ],
        count=82,
    )
    r = asyncio.run(_svc(fake).answer("Which compliance checks are overdue?", now=NOW))
    assert r["success"] and r["count"] == 2
    assert "2 compliance item(s) overdue" in r["formatted_response"]
    assert "Fire door inspection" in r["formatted_response"]
    assert "01 Jul 2026" in r["formatted_response"]
    assert "facilities team" in r["formatted_response"]


def test_overdue_sparql_is_namespace_scoped_full_iri():
    fake = _FakeSparql(rows=[_row("c1", "2026-07-01T00:00:00")], count=82)
    asyncio.run(_svc(fake).answer("anything overdue?", now=NOW))
    q = fake.queries[0]
    assert "<http://ontosage.org/capabilities#ComplianceCheck>" in q
    assert f'STRSTARTS(STR(?c), "{NS}")' in q
    assert 'recordStatus> "open"' in q and "FILTER NOT EXISTS" in q


def test_empty_register_declines_and_names_upload_path():
    fake = _FakeSparql(rows=[], count=0)
    r = asyncio.run(_svc(fake).answer("Which checks are overdue?", now=NOW))
    assert not r["success"]
    assert "No compliance register is loaded" in r["formatted_response"]
    assert "admin portal" in r["formatted_response"]


def test_loaded_register_with_nothing_overdue_is_positive():
    fake = _FakeSparql(rows=[], count=82)
    r = asyncio.run(_svc(fake).answer("Which checks are overdue?", now=NOW))
    assert r["success"] and r["count"] == 0
    assert "Nothing is overdue" in r["formatted_response"]


def test_due_soon_reports_horizon():
    fake = _FakeSparql(
        rows=[_row("check_ll_1", "2026-08-25T00:00:00", label="Legionella outlet flush")],
        count=82,
    )
    r = asyncio.run(_svc(fake).answer("What is due in the next 14 days?", now=NOW))
    assert r["success"] and r["horizon_days"] == 14 and r["count"] == 1
    assert "next 14 days" in r["formatted_response"]
    assert "Legionella outlet flush" in r["formatted_response"]


def test_last_done_with_next_due():
    fake = _FakeSparql(
        done_rows=[
            {"label": {"value": "Fire alarm weekly test"}, "done": {"value": "2026-08-10T09:00:00"}}
        ],
        due_rows=[{"due": {"value": "2026-08-24T00:00:00"}}],
        count=82,
    )
    r = asyncio.run(_svc(fake).answer("When was the fire alarm last tested?", now=NOW))
    assert r["success"] and r["found"] and r["item"] == "fire alarm"
    assert "10 Aug 2026" in r["formatted_response"]
    assert "24 Aug 2026" in r["formatted_response"]


def test_last_done_unknown_item_asks_which():
    fake = _FakeSparql(count=82)
    r = asyncio.run(_svc(fake).answer("When was the widget last tested?", now=NOW))
    assert not r["success"]
    assert "Which compliance item" in r["formatted_response"]
    assert "fire alarm" in r["formatted_response"]


def test_sparql_failure_is_honest():
    class _Boom:
        async def __call__(self, query):
            raise RuntimeError("graphdb down")

    r = asyncio.run(_svc(_Boom()).answer("anything overdue?", now=NOW))
    assert not r["success"]
    assert "couldn't read the compliance register" in r["formatted_response"]
