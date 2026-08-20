"""Phase 19 - unified user-report intake tests.

Covers the deterministic logic of ReportIntakeService (priority derivation,
category mapping, action classification, report-ID handling, acknowledgment
formatting) plus the create/status/list DB flows against a fake asyncpg pool.

No live Postgres needed - a FakePool records the SQL + params and returns
canned rows, so these run in CI alongside the other deterministic suites.
"""

from __future__ import annotations

import pytest

from orchestrator.services.report_intake_service import (
    INTENT_TO_CATEGORY,
    ReportIntakeService,
    get_report_intake_service,
)

# -- Pure-logic tests (no DB) ----------------------------------------------------


@pytest.fixture
def svc():
    return ReportIntakeService(postgres_manager=None)


def test_category_for_intent_maps_all_report_intents(svc):
    assert svc.category_for_intent("maintenance") == "maintenance"
    assert svc.category_for_intent("complaint") == "complaint"
    assert svc.category_for_intent("feedback") == "feedback"
    assert svc.category_for_intent("safety_report") == "safety"
    assert svc.category_for_intent("suggestion") == "suggestion"
    assert svc.category_for_intent("sensor_data") == "other"
    assert svc.category_for_intent(None) == "other"


def test_intent_to_category_table_complete():
    for intent in ("maintenance", "complaint", "feedback", "safety_report", "suggestion"):
        assert intent in INTENT_TO_CATEGORY


@pytest.mark.parametrize(
    "text,category,expected",
    [
        ("there is a fire in the server room", "safety", "URGENT"),
        ("there is a gas leak near the lifts", "complaint", "URGENT"),
        ("someone could get injured on the wet floor", "safety", "URGENT"),
        ("the light is broken in 3.01", "maintenance", "HIGH"),
        ("the heater is not working", "maintenance", "HIGH"),
        ("fire exit blocked by boxes", "safety", "URGENT"),
        ("the corridor is a bit untidy", "safety", "HIGH"),
        ("please add more bike racks", "suggestion", "LOW"),
        ("the new lighting is great", "feedback", "LOW"),
        ("the room is a little warm", "complaint", "NORMAL"),
    ],
)
def test_priority_derivation(svc, text, category, expected):
    assert svc._derive_priority(text, category) == expected


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("the light in 3.01 is broken", "create"),
        ("report a fault on floor 2", "create"),
        ("what is the status of REP-A1B2C3", "status"),
        ("check report REP-ABC123", "status"),
        ("any update on REP-123ABC", "status"),
        ("show my reports", "list"),
        ("list all my reports", "list"),
    ],
)
def test_action_classification(svc, msg, expected):
    assert svc.classify_action(msg) == expected


def test_report_id_extraction_and_normalisation(svc):
    assert svc.extract_report_id("check REP-A1B2C3 please") == "REP-A1B2C3"
    assert svc.extract_report_id("status of rep a1b2c3") == "REP-A1B2C3"
    assert svc.extract_report_id("REPA1B2C3") == "REP-A1B2C3"
    assert svc.extract_report_id("no id here") is None


def test_title_derivation_first_sentence(svc):
    t = svc._derive_title("The heater on floor 2 is not working. It has been cold all day.")
    assert t == "The heater on floor 2 is not working"


def test_title_derivation_truncates_long(svc):
    long = "x" * 200
    t = svc._derive_title(long)
    assert len(t) <= 91 and t.endswith("…")


def test_acknowledgment_contains_id_and_status(svc):
    msg = svc._acknowledgment("REP-ABC123", "maintenance", "HIGH", "room 3.01", "heater")
    assert "REP-ABC123" in msg
    assert "OPEN" in msg
    assert "room 3.01" in msg
    assert "heater" in msg


def test_acknowledgment_urgent_adds_emergency_note(svc):
    msg = svc._acknowledgment("REP-ABC123", "safety", "URGENT", None, None)
    assert "urgent" in msg.lower()
    assert "emergency" in msg.lower()


# -- DB-flow tests with a fake asyncpg pool --------------------------------------


class _FakeConn:
    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, sql, *params):
        self.parent.calls.append(("execute", sql, params))
        return "INSERT 0 1" if sql.strip().upper().startswith("INSERT") else "UPDATE 1"

    async def fetchrow(self, sql, *params):
        self.parent.calls.append(("fetchrow", sql, params))
        return self.parent.row

    async def fetch(self, sql, *params):
        self.parent.calls.append(("fetch", sql, params))
        return self.parent.rows


class _FakeAcquire:
    def __init__(self, parent):
        self.parent = parent

    async def __aenter__(self):
        return _FakeConn(self.parent)

    async def __aexit__(self, *a):
        return False


class _FakePool:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []
        self.calls = []

    def acquire(self):
        return _FakeAcquire(self)


class _FakePG:
    def __init__(self, row=None, rows=None):
        self.pool = _FakePool(row=row, rows=rows)


@pytest.mark.asyncio
async def test_create_report_inserts_and_acknowledges():
    pg = _FakePG()
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.create_report(
        description="the light in 3.01 is broken",
        building_id="bldg1",
        category="maintenance",
        reporter_id="alice",
        persona="facility_manager+occupant",
    )
    assert res["success"] is True
    assert res["report_id"].startswith("REP-")
    assert res["category"] == "maintenance"
    assert res["priority"] == "HIGH"
    insert_calls = [c for c in pg.pool.calls if c[0] == "execute" and "INSERT" in c[1]]
    assert insert_calls, "expected an INSERT"
    params = insert_calls[0][2]
    assert "facility_manager+occupant" in params


@pytest.mark.asyncio
async def test_create_report_unavailable_when_no_pool():
    svc = ReportIntakeService(postgres_manager=None)
    res = await svc.create_report(description="x", building_id="bldg1")
    assert res["success"] is False
    assert "unavailable" in res["message"].lower()


@pytest.mark.asyncio
async def test_get_status_found():
    row = {
        "id": "REP-ABC123",
        "title": "broken light",
        "category": "maintenance",
        "priority": "HIGH",
        "status": "IN_PROGRESS",
        "assignee": "facilities",
        "admin_notes": None,
        "resolved_at": None,
        "description": "broken light",
    }
    pg = _FakePG(row=row)
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.get_report_status("REP-ABC123", reporter_id="alice")
    assert res["success"] is True
    assert "IN_PROGRESS" in res["message"]
    assert "facilities" in res["message"]


@pytest.mark.asyncio
async def test_get_status_not_found():
    pg = _FakePG(row=None)
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.get_report_status("REP-ZZZZZZ", reporter_id="alice")
    assert res["success"] is False
    assert "couldn't find" in res["message"].lower()


@pytest.mark.asyncio
async def test_list_user_reports():
    rows = [
        {
            "id": "REP-1",
            "category": "maintenance",
            "priority": "HIGH",
            "status": "OPEN",
            "title": "a",
            "created_at": None,
        },
        {
            "id": "REP-2",
            "category": "complaint",
            "priority": "NORMAL",
            "status": "RESOLVED",
            "title": "b",
            "created_at": None,
        },
    ]
    pg = _FakePG(rows=rows)
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.list_user_reports("alice")
    assert res["success"] is True
    assert len(res["reports"]) == 2
    assert "REP-1" in res["message"] and "REP-2" in res["message"]


@pytest.mark.asyncio
async def test_update_status_resolved_sets_resolved_at():
    pg = _FakePG()
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.update_status("REP-ABC123", status="RESOLVED", assignee="bob")
    assert res["success"] is True
    upd = [c for c in pg.pool.calls if c[0] == "execute"][0]
    assert "resolved_at = NOW()" in upd[1]


@pytest.mark.asyncio
async def test_update_status_rejects_invalid_status():
    pg = _FakePG()
    svc = ReportIntakeService(postgres_manager=pg)
    res = await svc.update_status("REP-ABC123", status="NONSENSE")
    assert res["success"] is False
    assert "invalid status" in res["error"].lower()


def test_singleton_accessor_binds_pool_later():
    import orchestrator.services.report_intake_service as mod

    mod._service = None
    s1 = get_report_intake_service(None)
    assert s1.postgres is None
    pg = _FakePG()
    s2 = get_report_intake_service(pg)
    assert s2 is s1 and s2.postgres is pg
    mod._service = None
