# -*- coding: utf-8 -*-
"""2D-06 wave 7: four ways a register question was answered from the wrong place.

Scored live, the register oracle read 81/94 and the failures that remained were one class: a
question whose subject is an id, a floor or a facet was taken for something else.

1. "Who is in charge of the Level 5 general waste?" and "When is the Level 3 lab corridor fire
   door next due?" were answered "In Room 5.01 I can measure ...". The reach rule read "in charge
   of the" as a QUANTITY because "Level" follows it. A floor named "Level 5" is not a level of
   anything, and a question asking who or when-due is about a record.
2. "What is the asset of WTY-BMS-2024?" and "Who is the recorded owner of INC-2026-011?" selected
   no register although the id selector was in place. The graph INFERS, so every warranty is also
   an IntervalRecord, and nineteen prefixes (WTY, INC, PTW, TS, WO, BK, ...) came back under both
   the register and its parent. "Shared" decides nothing, so exactly the registers built on
   IntervalRecord lost id selection while those built on Record kept it.
3. "How many timetabled sessions on floor 1 are scheduled?" was declined and "Are any timetabled
   sessions with weekday Thursday scheduled?" answered "I did not find any weekday": 675 sessions
   is too many to narrate, but counting and filtering are not a narration's job.
4. "How many bookings are recorded in total?" and "How many bookings in Room 5.15 are confirmed?"
   went to the events lane ("32 booking(s) for the building today"). And the projection itself
   dropped "Room 5.15" without a word: it answered 11, every confirmed booking, where the room
   holds 3.
"""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

from orchestrator.services import record_registry as rr
from orchestrator.services import register_projection as rp
from orchestrator.services import routing_contract as rc
from tests.register_fixture_rows import ground_truth, lifted_rows
from tests.test_the_register_lane_answers_a_lookup_from_the_rows_end_to_end import _lane

pytestmark = pytest.mark.unit

TODAY = date(2026, 9, 20)


# ── 1. a floor called "Level 5" is not a level of something ─────────────────────────────────────


def _rule(question: str):
    ctx = SimpleNamespace(
        intent="general", normalized={}, ql=question.lower(), query=question, sr=None
    )
    return rc._r_unmeasured_quantity_is_reach(ctx)


@pytest.mark.parametrize(
    "question",
    [
        "Who is in charge of the Level 5 general waste?",
        "For my notes: When is the Level 3 lab corridor fire door next due?",
        "Who owns the Level 4 plant room?",
        "When is the fire alarm in the Level 2 corridor due for test?",
    ],
)
def test_a_question_about_a_record_is_never_read_as_a_reach_question(question):
    assert _rule(question) is None, question


@pytest.mark.parametrize(
    "question, expected",
    [
        ("Is there a voltage fluctuation that could put our hardware at risk?", "observability"),
        ("Any radon readings on floor 2?", "observability"),
        ("Are there any unusual spikes?", None),
    ],
)
def test_a_real_quantity_question_still_reaches_the_reach_lane(question, expected):
    assert _rule(question) == expected


def test_a_floor_written_as_a_level_number_is_not_a_quantity_slot():
    assert rc._UNVERBED_QUANTITY_RE.search("is the level 5 general waste ok") is None
    assert rc._UNVERBED_QUANTITY_RE.search("is there a sudden voltage level") is not None


# ── 2. an id selects its register, whatever the graph infers about it ────────────────────────────


def test_the_prefix_query_drops_a_parent_class_and_formats_cleanly():
    query = rr._ID_PREFIX_QUERY % {"values": "o:Warranty o:IntervalRecord"}
    assert "FILTER NOT EXISTS" in query and "rdfs:subClassOf+" in query
    assert query.count("o:Warranty o:IntervalRecord") == 2
    assert "%" not in query


@pytest.mark.parametrize(
    "question, expected",
    [
        ("For my notes: What is the asset of WTY-BMS-2024?", "Warranty"),
        ("Who is the recorded owner of INC-2026-011?", "IncidentRecord"),
        ("Which permit is PTW-2026-0416?", "Permit"),
        ("What is the title of TS-0510?", "TimetabledSession"),
        ("What is the status of WO-008?", "WorkOrder"),
    ],
)
def test_an_id_with_two_separators_selects_the_register_even_when_the_graph_infers_a_parent(
    question, expected
):
    """The index as the graph used to return it: every interval register ALSO under IntervalRecord."""
    classes = [
        rr.RecordClass(name, name, 10, ())
        for name in (
            "Warranty",
            "IncidentRecord",
            "Permit",
            "TimetabledSession",
            "WorkOrder",
            "IntervalRecord",
        )
    ]
    index = rr.index_id_prefixes(
        [
            ("Warranty", "WTY"),
            ("IntervalRecord", "WTY"),
            ("IncidentRecord", "INC"),
            ("IntervalRecord", "INC"),
            ("Permit", "PTW"),
            ("IntervalRecord", "PTW"),
            ("TimetabledSession", "TS"),
            ("IntervalRecord", "TS"),
            ("WorkOrder", "WO"),
            ("IntervalRecord", "WO"),
        ]
    )
    assert rr.class_for_record_id(question, classes, index).local_name == expected


def test_two_real_sibling_registers_sharing_a_prefix_are_still_ambiguous():
    classes = [rr.RecordClass(n, n, 5, ()) for n in ("Warranty", "Permit", "IntervalRecord")]
    index = rr.index_id_prefixes([("Warranty", "ZZ"), ("Permit", "ZZ"), ("IntervalRecord", "ZZ")])
    assert rr.class_for_record_id("What is ZZ-001?", classes, index) is None


# ── 3. a count or a facet over a register too large to narrate ──────────────────────────────────


def test_the_timetable_is_filtered_by_floor_and_by_weekday_from_the_rows():
    rows, label = lifted_rows("timetabled_sessions.md")
    terms = ("timetabled session", "timetable")
    floor = rp.deterministic_answer(
        rows,
        "How many timetabled sessions on floor 1 are scheduled?",
        label,
        TODAY,
        register_terms=terms,
    )
    truth = [
        r
        for r in ground_truth("timetabled_sessions.md")
        if str(r["floor"]) == "1" and str(r["_status"]).lower() == "scheduled"
    ]
    assert floor.startswith(f"**{len(truth)} of the {len(rows)} records"), floor[:120]
    thursday = rp.deterministic_answer(
        rows,
        "Are any timetabled sessions with weekday Thursday scheduled?",
        label,
        TODAY,
        register_terms=terms,
    )
    assert thursday.startswith("**Yes**")


def test_the_lane_reads_a_large_register_whole_and_counts_it(monkeypatch):
    agent, calls = _lane(
        "timetabled_sessions.md",
        "TimetabledSession",
        "Timetabled session",
        monkeypatch,
        instances=675,
        lay="timetabled sessions|teaching sessions",
    )
    state = SimpleNamespace(building_id=None, intermediate_results={})
    out = asyncio.run(
        agent._whole_register(state, "How many timetabled sessions on floor 1 are scheduled?")
    )
    assert out is not None and out["method"] == "whole_register"
    truth = [
        r
        for r in ground_truth("timetabled_sessions.md")
        if str(r["floor"]) == "1" and str(r["_status"]).lower() == "scheduled"
    ]
    assert out["formatted_response"].startswith(f"**{len(truth)} of the")
    assert not calls["llm"], "the model was asked to count a register it can be shown the rows of"


def test_a_question_no_lookup_answers_does_not_pay_for_the_whole_read(monkeypatch):
    agent, _calls = _lane(
        "timetabled_sessions.md",
        "TimetabledSession",
        "Timetabled session",
        monkeypatch,
        instances=675,
        lay="timetabled sessions",
        llm="narrated",
    )
    seen = []
    original = agent._execute_query

    async def counting(query, *a, **k):
        seen.append(query)
        return await original(query, *a, **k)

    agent._execute_query = counting
    state = SimpleNamespace(building_id=None, intermediate_results={})
    asyncio.run(
        agent._register_projected_whole(
            SimpleNamespace(
                local_name="TimetabledSession", label="Timetabled session", instances=675, terms=()
            ),
            "Tell me about the timetable",
            state,
        )
    )
    assert seen == []


# ── 4. booking questions about the record, and a room the projection used to drop ────────────────


@pytest.mark.parametrize(
    "question",
    [
        "how many bookings are recorded in total?",
        "how many bookings in Room 5.15 are confirmed?",
        "Are any bookings provisional?",
        "Which bookings are cancelled?",
    ],
)
def test_a_question_about_the_booking_record_belongs_to_the_register(question):
    assert rc.booking_register_question(question)
    assert not rc.events_question(question)
    assert rc.register_owns_the_record(question)


@pytest.mark.parametrize(
    "question",
    [
        "Is Room 5.15 free this afternoon?",
        "how many bookings are there today?",
        "how many bookings in Room 5.15 are confirmed today?",
        "Which meeting rooms are booked this afternoon?",
        "Is anything booked right now?",
    ],
)
def test_a_question_about_the_present_moment_stays_with_the_events_lane(question):
    assert not rc.booking_register_question(question)
    assert rc.events_question(question)


def test_a_named_room_is_a_filter_not_a_dropped_word():
    rows, label = lifted_rows("room_bookings.md")
    text = rp.deterministic_answer(
        rows,
        "how many bookings in Room 5.15 are confirmed?",
        label,
        TODAY,
        register_terms=("booking", "bookings"),
    )
    truth = [
        r
        for r in ground_truth("room_bookings.md")
        if "5.15" in r["room"] and r["status"] == "Confirmed"
    ]
    assert len(truth) == 3
    assert text.startswith(f"**{len(truth)} of the 16 records")
    assert all(r["_id"] in text for r in truth)


def test_a_room_no_record_carries_is_not_answered_with_every_booking():
    rows, label = lifted_rows("room_bookings.md")
    q = "how many bookings in Room 9.99 are confirmed?"
    assert rp.deterministic_answer(rows, q, label, TODAY, register_terms=("booking",)) == ""
    assert rp.facts_lines(rows, q, label, TODAY, register_terms=("booking",)) == []


def test_loading_the_index_sends_the_held_classes_and_indexes_what_comes_back(monkeypatch):
    """The whole load path, with the graph stubbed: the query is formatted with the held classes
    and the rows it returns become the index, so a formatting slip cannot fail silently."""
    from orchestrator.services import ontology_manager

    sent = []

    async def fake_select(query, limit=100):
        sent.append(query)
        return {
            "ok": True,
            "rows": [
                {"cls": "http://ontosage.org/capabilities#Warranty", "prefix": "WTY", "n": "7"},
                {"cls": "http://ontosage.org/capabilities#IncidentRecord", "prefix": "INC"},
            ],
        }

    monkeypatch.setattr(ontology_manager, "run_sparql_select", fake_select)
    rr._ID_PREFIXES.clear()
    found = [
        rr.RecordClass("Warranty", "Warranty", 7, ()),
        rr.RecordClass("IncidentRecord", "Incident", 15, ()),
    ]
    try:
        asyncio.run(rr._load_id_prefixes(found))
        assert "o:Warranty o:IncidentRecord" in sent[0] and "%" not in sent[0]
        assert rr._ID_PREFIXES == {"WTY": {"Warranty"}, "INC": {"IncidentRecord"}}
        assert rr.held_record_class("Who owns WTY-BMS-2024?", found).local_name == "Warranty"
    finally:
        rr._ID_PREFIXES.clear()
