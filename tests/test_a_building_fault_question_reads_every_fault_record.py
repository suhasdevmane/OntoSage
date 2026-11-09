"""BUG-1682 (P1): "Are any sensors or building services reporting faults right now?"

Answered live (2026-11-07) *"No faults reported. All sensors show no fault status in the current
data set"* by a reading lane, while the building held eight uncleared alarms, fifteen equipment
outages in progress and assets marked out of service. A reading is not where a fault is recorded,
so that lane could only ever say "none". `fault_overview` reads the four places a fault IS
recorded, reports each separately, and says "not checked" -- never "none" -- for one it could not
read.
"""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from orchestrator.services import fault_overview as fo

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
NS = "http://example.org/anybldg#"
NOW = datetime(2026, 11, 7, 10, 0, 0)


# ── which questions these are ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "q",
    [
        "Are any sensors or building services reporting faults right now?",
        "Is anything in the building faulty at the moment?",
        "Are there any active alarms?",
        "Is anything broken in the building?",
        "What faults are there right now?",
        "Any equipment out of service?",
    ],
)
def test_a_building_wide_fault_question_is_one(q):
    assert fo.is_building_fault_question(q)


@pytest.mark.parametrize(
    "q",
    [
        "Are the lifts working?",  # a named family: asset_state's own classifier
        "The lift is broken.",  # a statement files a ticket
        "How do I report a fault?",  # a procedure
        "Were there any faults last week?",  # a period: history, not now
        "Are there any faults in room 2.01?",  # a named place
        "Is the projector in room 1.25 broken?",
        "What is a fault?",  # what the word means
        "Are any accessible facilities out of service right now?",  # a named kind
    ],
)
def test_anything_naming_a_thing_a_place_or_a_period_is_not(q):
    assert not fo.is_building_fault_question(q)


def test_blast_radius_over_the_bank_is_zero():
    """Measured 2026-11-07. A wider first version matched 16 bank questions, most of them
    specialist compound questions caught by 'issue', 'failure' or 'wrong'; those words were
    removed and every other word of a match must be generic."""
    bank = REPO / "docs" / "smart_building_questions.csv"
    if not bank.is_file():
        pytest.skip("bank not present")
    qs = [r["Question"] for r in csv.DictReader(bank.open(encoding="utf-8-sig"))]
    assert len(qs) > 4000
    assert [q for q in qs if fo.is_building_fault_question(q)] == []


# ── reading the four sources ────────────────────────────────────────────────────────────────


def _binding(**kw):
    return {k: {"value": v} for k, v in kw.items()}


def _sparql(alarms, statuses):
    async def run(q):
        if "AlarmEvent" in q:
            return {"results": {"bindings": alarms}}
        if "AssetStatus" in q:
            return {"results": {"bindings": statuses}}
        return {"results": {"bindings": []}}

    return run


class _Events:
    def __init__(self, outages=(), stuck=(), work=()):
        self.outages, self.stuck, self.work = list(outages), list(stuck), list(work)

    def build_active_now(self, event_type, **_):
        return f"ACTIVE {event_type}"

    def build_overlap_window(self, event_type, start, end, **_):
        return f"OVERLAP {event_type}"

    def build_count_by_status(self, event_type, **_):
        return f"COUNT {event_type}"

    async def execute_query(self, sql):
        if sql == "ACTIVE asset_outage":
            return SimpleNamespace(rows=self.outages)
        if sql == "OVERLAP anomaly:stuck":
            return SimpleNamespace(rows=self.stuck)
        if sql.startswith("OVERLAP"):
            return SimpleNamespace(rows=[])
        if sql == "COUNT workorder":
            return SimpleNamespace(rows=self.work)
        return SimpleNamespace(rows=[])


ALARMS = [
    _binding(
        a=f"{NS}A1",
        label="Detector fault - Zone 2",
        id="ALM-1",
        prio="HIGH",
        status="detected",
        **{"from": "2026-09-16T13:52:38"},
    ),
    _binding(
        a=f"{NS}A2",
        label="Low flow",
        id="ALM-2",
        prio="LOW",
        status="open",
        **{"from": "2026-09-17T13:28:00"},
    ),
    _binding(
        a=f"{NS}A3",
        label="Old trip",
        id="ALM-3",
        prio="HIGH",
        status="resolved",
        **{"from": "2026-07-09T16:12:18"},
    ),
    _binding(
        a=f"{NS}A4",
        label="Ended",
        id="ALM-4",
        prio="MEDIUM",
        status="detected",
        **{"from": "2026-08-01T10:00:00", "to": "2026-08-01T12:00:00"},
    ),
]
STATUSES = [
    _binding(
        s=f"{NS}S1",
        asset=f"{NS}WaterPoint_2b",
        label="Bottle-filling station",
        v="out_of_service",
        reason="supply isolated",
    ),
    _binding(s=f"{NS}S2", asset=f"{NS}Lift1", label="Lift 1", v="operational"),
]
OUTAGE = {
    "event_id": "e1",
    "event_type": "asset_outage",
    "subject_uuid": "u",
    "start_dt": "2026-11-05 14:35:00",
    "end_dt": None,
    "status": "open",
    "attrs": json.dumps({"asset": "av_Room0.19", "reason": "firmware update", "asset_kind": "av"}),
}


def _answer(events):
    return asyncio.run(
        fo.answer(
            "Is anything faulty?", _sparql(ALARMS, STATUSES), NS, events, "Some Building", now=NOW
        )
    )


def test_every_standing_fault_is_counted_by_its_own_source():
    ev = _Events(
        outages=[OUTAGE],
        stuck=[{"subject_uuid": "s1"}, {"subject_uuid": "s2"}],
        work=[{"status": "open", "n": 5}, {"status": "done", "n": 90}],
    )
    out = _answer(ev)
    text = out["formatted_response"]
    assert text.startswith("**Yes — 6 faults are recorded as standing right now**")
    assert "**Alarms not cleared, 1 of them high priority: 2**" in text
    assert "Detector fault - Zone 2 — high priority, detected" in text
    assert "Old trip" not in text and "Ended" not in text  # resolved, and ended before now
    assert "AV equipment, Room 0.19 — firmware update" in text
    assert "Bottle-filling station — out of service (supply isolated)" in text
    assert "Lift 1" not in text
    assert "**Sensors with an instrument fault in the last 24 hours: 2**" in text
    assert "5 maintenance work orders are open or assigned" in text
    assert out["fault_overview"]["the alarm log"] == 2


def test_none_is_said_only_when_every_source_was_read():
    out = asyncio.run(
        fo.answer("Is anything faulty?", _sparql([], []), NS, _Events(), "B", now=NOW)
    )
    assert out["formatted_response"].startswith("**No fault is recorded as standing right now**")


def test_an_unreadable_source_is_not_checked_never_none():
    out = asyncio.run(fo.answer("Is anything faulty?", _sparql([], []), NS, None, "B", now=NOW))
    text = out["formatted_response"]
    assert text.startswith("**I found no standing fault in the records I could read**")
    assert "the events log" in text and "not a clean bill of health" in text
    assert out["fault_overview"]["the events log"] is None


# ── routing ─────────────────────────────────────────────────────────────────────────────────


def test_the_lanes_own_predicate_accepts_it_so_the_post_stage_rule_keeps_it():
    from orchestrator.services.asset_state_service import is_asset_state_question

    assert is_asset_state_question(
        "Are any sensors or building services reporting faults right now?"
    )


def test_the_parse_stage_rule_sends_it_to_asset_state_and_is_last():
    from orchestrator.services import routing_contract as rc

    assert rc.PARSE_STAGE_RULES[-1].name == "building_fault_status"
    ctx = SimpleNamespace(
        query="Is anything in the building faulty at the moment?",
        sr=SimpleNamespace(is_control_command=lambda q: False, report_intake_intent=lambda q: None),
    )
    assert rc._r_building_fault_status(ctx) == "asset_state"
    ctx.query = "The lift is broken."
    assert rc._r_building_fault_status(ctx) is None


# ── 2026-11-07: a duty's scope is not a person's location ───────────────────────────────────


@pytest.mark.parametrize(
    "q,refused",
    [
        ("Who is responsible for fire safety in the building?", False),
        ("Who is in the building right now?", True),
        ("Who manages this building and is she in her office?", True),
        ("Is the professor in the building?", True),
    ],
)
def test_who_is_responsible_in_the_building_is_governance(q, refused):
    from orchestrator.services.privacy.inference_classes import classify_inference

    assert bool(classify_inference(q)) is refused


def test_every_figure_in_the_answer_is_backed_for_the_numeric_guard():
    """Live 2026-11-07: the guard withheld the whole overview -- the text quoted dates and room
    numbers and the payload held only four totals. The items now ride on the payload."""
    from orchestrator.services.numeric_guard import guard_payload

    ev = _Events(
        outages=[OUTAGE],
        stuck=[{"subject_uuid": "s1"}, {"subject_uuid": "s2"}],
        work=[{"status": "open", "n": 5}, {"status": "done", "n": 90}],
    )

    def _fmt(d):
        return f"{d.day} {d.strftime('%b %Y')}"

    payload = asyncio.run(
        fo.answer(
            "Is anything faulty?",
            _sparql(ALARMS, STATUSES),
            NS,
            ev,
            "Some Building",
            fmt_local=_fmt,
            now=NOW,
        )
    )
    guarded = guard_payload(payload, "asset_state")
    assert not guarded.get("guard_violations"), guarded.get("guard_violations")
    assert guarded["formatted_response"] == payload["formatted_response"]


# ── TODO-1642: an amenity with a status record is asked about by its own lane ───────────────


@pytest.mark.parametrize(
    "q,kind",
    [
        ("Is the water fountain on floor 2 working?", "water_point"),
        ("Are any drinking water points out of order?", "water_point"),
        ("Is the hearing loop on floor 1 working?", "accessibility"),
        ("Is the defibrillator working?", "first_aid"),
        ("Is drinking water available on floor 3?", None),  # where one is, not whether it works
        ("Is a study area available now?", None),  # seats, not service state
        ("For one hour of quiet work, which study area is best?", None),
    ],
)
def test_amenity_state_questions_reach_the_asset_state_lane(q, kind):
    from orchestrator.services.asset_state_service import classify_asset_question

    assert classify_asset_question(q) == kind


def test_a_named_floor_narrows_to_the_records_whose_labels_name_it():
    from orchestrator.services.asset_state_service import AssetStateService

    rows = [
        _binding(
            asset=f"{NS}WP0a",
            label="Bottle-filling station — Floor 0 (one end)",
            value="operational",
            observed="2026-11-07T09:00:00",
        ),
        _binding(
            asset=f"{NS}WP2a",
            label="Bottle-filling station — Floor 2 (one end)",
            value="operational",
            observed="2026-11-07T09:00:00",
        ),
        _binding(
            asset=f"{NS}WP2b",
            label="Bottle-filling station — Floor 2 (other end)",
            value="out_of_service",
            observed="2026-11-07T09:00:00",
        ),
    ]

    async def run(q):
        return {"results": {"bindings": rows}}

    svc = AssetStateService(run, NS)
    out = asyncio.run(svc.answer("Is the water fountain on floor 2 working?"))
    text = out["formatted_response"]
    assert "1 of 2 drinking-water point(s) on floor 2 are not operational" in text
    assert "Floor 2 (other end)" in text and "Floor 0" not in text


# ── CAVEAT-1718: an uploader graph whose file is gone is reported, never dropped ────────────


def test_an_uploader_graph_with_no_source_file_is_reported(monkeypatch):
    from pathlib import Path

    from orchestrator.services import ontology_manager, ttl_uploader

    async def graphs():
        return {
            "urn:ontosage:ttl:bldg_a.ttl": 10,
            "urn:ontosage:ttl:gone.ttl": 11,
            "http://example.org/documents/x": 5,  # not the uploader's: not this audit's business
        }

    monkeypatch.setattr(ontology_manager, "list_named_graphs", graphs)
    out = asyncio.run(ttl_uploader.audit_orphan_graphs([Path("input/bldg_a.ttl")]))
    assert out["orphans"] == [{"graph": "urn:ontosage:ttl:gone.ttl", "triples": 11}]


# ── follow-ups that point at a counted thing or at the reply's one record ───────────────────


def test_the_service_after_a_reply_naming_one_record_is_that_record():
    from orchestrator.services.context_switch import resolve_sole_record_anaphor

    prev = "The soonest next due date on record is **16 December 2026** — **SVC-14** (Lift LOLER examination)."
    assert (
        resolve_sole_record_anaphor("Who carries out the service?", prev)
        == "Who carries out SVC-14?"
    )
    assert (
        resolve_sole_record_anaphor("What is the service schedule for the building?", prev) is None
    )
    assert resolve_sole_record_anaphor("Who is the service provider?", prev) is None


def test_which_room_has_the_most_takes_the_counted_thing_from_the_earlier_question():
    from orchestrator.services.context_switch import resolve_elliptical_superlative

    assert (
        resolve_elliptical_superlative(
            "Which room has the most?", ["How many lectures are there this week?"]
        )
        == "Which room has the most lectures this week?"
    )
