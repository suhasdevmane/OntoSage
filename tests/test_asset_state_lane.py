# -*- coding: utf-8 -*-
"""Service and asset state: data that existed and nothing read (V6-T58/T60, 2026-08-25).

The provisioner had been writing ``ontosage:AssetStatus`` and ``ontosage:ServiceSchedule``
triples for weeks — 21 status records on this building, each with a value, an observation
time and an assistance contact — and no code anywhere referenced them. Measured live:
"are the lifts working?" answered *"this building does not have lift sensors"* while the
lift's status sat in the graph.

That is the described-but-unconnected failure in a third form. Not a sensor with no data,
and not a file nothing ingests, but **data nothing queries**.

Two things this lane must get right, because a service state is not a sensor reading:

* **It is a last-known state, not a live one.** A status observed five days ago is not a
  statement about now, and the answer says so.
* **An outage without a contact is a worse answer than it looks.** When something is out
  of service, the assistance contact travels with the answer.
"""

from datetime import datetime, timedelta, timezone

import pytest

from orchestrator.services.asset_state_service import (
    STALE_AFTER_HOURS,
    AssetStateService,
    classify_asset_question,
    is_asset_state_question,
)

pytestmark = pytest.mark.unit

_NS = "http://example.org/bldg#"
_NOW = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)


def _bindings(rows):
    return {"results": {"bindings": [{k: {"value": v} for k, v in r.items()} for r in rows]}}


def _exec(rows):
    async def run(_query):
        return _bindings(rows)

    return run


# ── classification ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "question,expected",
    [
        ("Are the lifts working?", "lift"),
        ("Is the elevator out of order?", "lift"),
        ("Is the AV equipment in the seminar rooms working?", "av"),
        ("Is the projector broken?", "av"),
        ("Is the wifi working on floor 3?", "network"),
        ("Is the network down?", "network"),
        ("When was the last cleaning of floor 2?", "schedule"),
        ("Are there any planned closures coming up?", "closure"),
        # not this lane
        ("Where is the lift?", None),
        ("What is the CO2 in room 5.01?", None),
        ("How many lifts does the building have?", None),
        ("", None),
    ],
)
def test_classification(question, expected):
    assert (
        classify_asset_question(question) is expected
        or classify_asset_question(question) == expected
    )


def test_state_word_is_required():
    """'where is the lift' is wayfinding; only a STATE question belongs here."""
    assert is_asset_state_question("Where is the lift?") is False
    assert is_asset_state_question("Is the lift working?") is True


def test_schedule_pattern_does_not_poach_equipment_service_history():
    """The first version matched 'serviced' and 'maintenance', which took
    'when was chiller 7 last serviced?' from the capability/register lanes and
    'scheduled maintenance' from the maintenance route. A lane must claim only the
    questions its own data can answer."""
    assert classify_asset_question("When was chiller 7 last serviced?") is None
    assert classify_asset_question("When is the next scheduled maintenance?") is None


# ── status answers ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_all_operational_reports_the_count_and_the_check_time():
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "label": "Lift 1",
                    "value": "operational",
                    "observed": (_NOW - timedelta(hours=2)).isoformat(),
                }
            ]
        ),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["success"] is True
    assert out["total"] == 1 and out["not_operational"] == 0
    assert "operational" in out["formatted_response"]


@pytest.mark.asyncio
async def test_an_outage_names_the_asset_and_who_to_contact():
    """An outage report with no route to help is a worse answer than it looks."""
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "label": "Lift 1",
                    "value": "out_of_service",
                    "observed": (_NOW - timedelta(hours=1)).isoformat(),
                    "contact": "Estates helpdesk, ext 1234",
                },
                {
                    "asset": _NS + "Lift2",
                    "label": "Lift 2",
                    "value": "operational",
                    "observed": (_NOW - timedelta(hours=1)).isoformat(),
                },
            ]
        ),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["not_operational"] == 1
    text = out["formatted_response"]
    assert "Lift 1" in text
    assert "Estates helpdesk, ext 1234" in text


@pytest.mark.asyncio
async def test_a_stale_status_is_reported_as_last_known_not_as_now():
    """A status observed days ago is not a statement about the present."""
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "value": "operational",
                    "observed": (_NOW - timedelta(hours=STALE_AFTER_HOURS + 48)).isoformat(),
                }
            ]
        ),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert "last KNOWN state" in out["formatted_response"]


@pytest.mark.asyncio
async def test_an_unreadable_timestamp_is_not_given_a_default_age():
    """A guessed age would let a stale status be presented as current."""
    svc = AssetStateService(
        _exec([{"asset": _NS + "Lift1", "value": "operational", "observed": "not-a-date"}]),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["oldest_observation_hours"] is None
    assert "unknown time" in out["formatted_response"]


@pytest.mark.asyncio
async def test_simulated_status_declares_itself():
    """Declared simulation is honest; undeclared simulation is fabrication."""
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "value": "operational",
                    "observed": _NOW.isoformat(),
                    "simulated": "true",
                }
            ]
        ),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["simulated"] is True
    assert "simulated" in out["formatted_response"].lower()


@pytest.mark.asyncio
async def test_no_records_declines_and_names_the_unlock_path():
    svc = AssetStateService(_exec([]), _NS)
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["success"] is False
    assert "no code change" in out["formatted_response"]


@pytest.mark.asyncio
async def test_no_closures_says_so_without_claiming_none_are_planned():
    """'None recorded' is a statement about the model, not about the world."""
    svc = AssetStateService(_exec([]), _NS)
    out = await svc.answer("Are there any planned closures coming up?", now=_NOW)
    assert out["count"] == 0
    assert "not a guarantee" in out["formatted_response"]


@pytest.mark.asyncio
async def test_a_query_failure_declines_rather_than_raising():
    async def boom(_q):
        raise RuntimeError("graph down")

    svc = AssetStateService(boom, _NS)
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["success"] is False


# ── routing ──────────────────────────────────────────────────────────────────
def test_a_fault_STATEMENT_still_reaches_intake():
    """'the lift is broken' is a report. Only questions belong to this lane."""
    from orchestrator.services import routing_contract as rc

    norm = {"intent": "maintenance", "analytics": False, "general": False}
    rc.apply_contract("The lift is broken.", norm, "parse")
    assert norm["intent"] == "maintenance"


@pytest.mark.parametrize(
    "question",
    [
        "Are the lifts working?",
        "Is the wifi working on floor 3?",
        "Are there any planned closures coming up?",
    ],
)
def test_state_questions_reach_the_asset_lane(question):
    from orchestrator.services import routing_contract as rc

    norm = {"intent": "capability", "analytics": False, "general": False}
    rc.apply_contract(question, norm, "parse")
    assert norm["intent"] == "asset_state"


def test_closure_question_does_not_file_a_ticket():
    """It was classified maintenance and the intake path FILED one (REP-E1A800)."""
    from orchestrator.services import routing_contract as rc

    norm = {"intent": "maintenance", "analytics": False, "general": False}
    rc.apply_contract("Are there any planned closures coming up?", norm, "parse")
    assert norm["intent"] == "asset_state"


def test_capability_short_circuit_is_bypassed_for_state_questions():
    """The probe claims the question before the LLM and the parse stage never runs on
    that path, so the routing rule could not get a say however it was ordered."""
    import inspect

    from orchestrator.agents import dialogue_agent

    src = inspect.getsource(dialogue_agent)
    assert "_is_asset_state_question(user_query)" in src


def test_the_lane_result_is_collected_by_the_response_node():
    """Steps 1 and 2 passing their tests does not prove step 3 happened: a lane can
    route, run, compute the right answer, and the user still sees 'I processed your
    request, but couldn't generate a response.'"""
    import inspect

    from orchestrator.workflow import _orchestrator

    src = inspect.getsource(_orchestrator)
    assert 'state.intermediate_results.get("asset_state_result")' in src
    assert '_asset_state_result["formatted_response"]' in src


# ── outage episodes: a status is not a fact ──────────────────────────────────
class _FakeEventsAdapter:
    """Minimal stand-in: build_active_now + execute_query, the two the lane uses."""

    def __init__(self, rows):
        self._rows = rows
        self.last_sql = None

    def build_active_now(self, event_type, subject_uuids=None, at=None, limit=500):
        self.last_sql = f"SELECT ... {event_type} {sorted(subject_uuids or [])}"
        return self.last_sql

    async def execute_query(self, sql):
        class _Result:
            rows = self._rows

        return _Result()


def _outage_row(building_id, asset_local, start, reason="controller fault"):
    """A row shaped like the adapter's SELECT: (id, type, subject, start, end, status, attrs)."""
    import json

    from orchestrator.services.deliberation.synthetic_events import subject_uuid

    return (
        "eid",
        "asset_outage",
        subject_uuid(building_id, asset_local),
        start.isoformat(),
        None,
        "open",
        json.dumps({"asset": asset_local, "reason": reason}),
    )


def test_outages_never_start_in_the_future():
    from orchestrator.services.deliberation.synthetic_events import outages_for_day

    now = datetime(2026, 8, 25, 12, 0)
    assets = [(f"Lift{i}", "lift") for i in range(40)]
    for offset in (0, 1, 3):
        day = datetime(2026, 8, 25) + timedelta(days=offset)
        for e in outages_for_day("b", assets, day, now):
            assert e["start_dt"] <= now, e


def test_outages_both_clear_and_linger():
    """An estate where nothing ever clears is as untestable as one where nothing breaks."""
    from orchestrator.services.deliberation.synthetic_events import outages_for_day

    now = datetime(2026, 8, 25, 12, 0)
    assets = [(f"Lift{i}", "lift") for i in range(60)]
    statuses = set()
    for offset in range(-30, 1):
        day = datetime(2026, 8, 25) + timedelta(days=offset)
        for e in outages_for_day("b", assets, day, now):
            statuses.add(e["status"])
    assert statuses == {"open", "done"}, statuses


def test_outage_generation_is_deterministic():
    from orchestrator.services.deliberation.synthetic_events import outages_for_day

    now = datetime(2026, 8, 25, 12, 0)
    assets = [(f"Lift{i}", "lift") for i in range(30)]
    day = datetime(2026, 8, 20)
    a = outages_for_day("b", assets, day, now)
    b = outages_for_day("b", assets, day, now)
    assert [e["event_id"] for e in a] == [e["event_id"] for e in b]


@pytest.mark.asyncio
async def test_an_open_episode_outranks_a_stale_operational_triple():
    """The triple says what was true when the asset was described; the episode says what
    is true now, and where they disagree the live one wins."""
    from shared.config import settings

    events = _FakeEventsAdapter(
        [_outage_row(settings.BUILDING_ID, "Lift1", _NOW - timedelta(hours=5))]
    )
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "label": "Lift 1",
                    "value": "operational",
                    "observed": (_NOW - timedelta(days=6)).isoformat(),
                    "contact": "Estates helpdesk",
                }
            ]
        ),
        _NS,
        events_adapter=events,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["not_operational"] == 1
    assert "controller fault" in out["formatted_response"]
    assert "Estates helpdesk" in out["formatted_response"]


@pytest.mark.asyncio
async def test_a_live_outage_says_since_not_last_checked():
    """'out of service since 47 hours' and 'this is not a live state' tell the reader
    two different things about the same fact."""
    from shared.config import settings

    events = _FakeEventsAdapter(
        [_outage_row(settings.BUILDING_ID, "Lift1", _NOW - timedelta(hours=47))]
    )
    svc = AssetStateService(
        _exec([{"asset": _NS + "Lift1", "value": "operational", "observed": _NOW.isoformat()}]),
        _NS,
        events_adapter=events,
    )
    text = (await svc.answer("Are the lifts working?", now=_NOW))["formatted_response"]
    assert "out of service since" in text
    assert "last KNOWN state" not in text


@pytest.mark.asyncio
async def test_the_rendered_age_travels_in_the_payload():
    """_human_age rounds hours into days for display ("15 days ago"), and 15 appears
    nowhere else — so the numeric guard suppressed a correct answer for a figure
    computed only for the prose."""
    svc = AssetStateService(
        _exec(
            [
                {
                    "asset": _NS + "Lift1",
                    "value": "operational",
                    "observed": (_NOW - timedelta(days=15)).isoformat(),
                }
            ]
        ),
        _NS,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["last_observation_phrase"] in out["formatted_response"]

    from orchestrator.services.numeric_guard import collect, find_unbacked

    allowed, blobs = set(), []
    collect(out, allowed, blobs)
    assert find_unbacked(out["formatted_response"], allowed, blobs) == []


@pytest.mark.asyncio
async def test_no_events_adapter_still_answers_from_the_graph():
    """A building with no event store keeps working on the static status alone."""
    svc = AssetStateService(
        _exec([{"asset": _NS + "Lift1", "value": "operational", "observed": _NOW.isoformat()}]),
        _NS,
        events_adapter=None,
    )
    out = await svc.answer("Are the lifts working?", now=_NOW)
    assert out["success"] is True and out["not_operational"] == 0
