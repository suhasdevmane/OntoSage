"""The Paper 3 study export joins Open WebUI turns, turn_memory rows and log lines correctly.

Tracker rows D1/D2/D4. Pure functions only: no stack, no building, no Docker.
"""

import datetime as dt
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PATH = Path(__file__).resolve().parents[1] / "scripts" / "export_study_turns.py"
_spec = importlib.util.spec_from_file_location("export_study_turns", _PATH)
est = importlib.util.module_from_spec(_spec)
sys.modules["export_study_turns"] = est
_spec.loader.exec_module(est)


def _turn(q, asked, answered, answer="ok"):
    return {
        "question": q,
        "asked_at": asked,
        "answered_at": answered,
        "answer": answer,
        "evidence_panel": "",
        "message_id": "m",
        "turn": 0,
    }


def test_split_answer_separates_the_evidence_panel():
    raw = 'CO2 was 540 ppm.\n\n<details type="evidence">\n<summary>How I know this</summary>\nSources (1)\n</details>'
    text, panel = est.split_answer(raw)
    assert text == "CO2 was 540 ppm."
    assert panel.startswith('<details type="evidence">')


def test_align_matches_by_text_then_marks_a_missing_row_unjoined():
    turns = [
        _turn("What is the CO2 in room 5.17?", 1, 2),
        _turn("and yesterday?", 3, 4),
        _turn("thanks", 5, 6),
    ]
    rows = [
        {"turn_index": 1, "user_query": "What is the CO2 in room 5.17?"},
        {"turn_index": 2, "user_query": "What was the CO2 in room 5.17 yesterday?"},
    ]
    out = est.align(turns, rows)
    assert out[0]["aligned_by"] == "text"
    assert out[1] is not None and out[1]["turn_index"] == 2  # a co-reference rewrite still aligns
    assert out[2] is None


def test_align_falls_back_to_order_only_when_counts_agree():
    turns = [_turn("a", 1, 2), _turn("b", 3, 4)]
    rows = [{"turn_index": 1, "user_query": "zzz"}, {"turn_index": 2, "user_query": "yyy"}]
    assert [r["aligned_by"] for r in est.align(turns, rows)] == ["order", "order"]
    assert est.align(turns, rows[:1]) == [
        None,
        None,
    ]  # unequal counts and no text evidence: unjoined
    assert est.align(turns, []) == [None, None]


def test_window_events_reads_route_gate_and_provider_and_flags_a_shared_window():
    log = est.parse_log(
        [
            "2026-10-15 09:00:01,000 - x - INFO - Starting workflow execution for conversation owui_abc-1:openwebui_user",
            "2026-10-15 09:00:05,000 - x - INFO - Final intent for routing: deliberate",
            "2026-10-15 09:00:06,000 - x - WARNING - relevance gate replaced a sensor_data answer: OFF_TOPIC",
            "2026-10-15 09:00:07,000 - x - ERROR - [hosted] gateway unreachable (ReadTimeout: ); refusing without queueing",
            "2026-10-15 09:00:08,000 - x - INFO - Starting workflow execution for conversation owui_zzz-9:openwebui_user",
        ]
    )
    start = dt.datetime(2026, 10, 15, 9, 0, 0, tzinfo=dt.timezone.utc)
    ev = est.window_events(log, start, start + dt.timedelta(seconds=10), conversation_hint="abc-1")
    assert ev["route_final"] == "deliberate"
    assert ev["relevance_gate"] and "replaced" in ev["relevance_gate"][0]
    assert ev["provider_log"]
    assert ev["log_window_shared"] == 1


def test_provider_flags_separate_explicit_failures_from_suspected_ones():
    assert est.provider_flags(
        "The language model that writes the summary is not responding at the moment", []
    ) == (1, 0)
    assert est.provider_flags("I couldn't read the register just now.", []) == (0, 1)
    assert est.provider_flags("Room 5.17 averaged 540 ppm.", ["[hosted] gateway unreachable"]) == (
        1,
        0,
    )
    assert est.provider_flags("Room 5.17 averaged 540 ppm.", []) == (0, 0)


def test_check_counts_reads_the_stored_evidence_record():
    ev = {
        "status": "measured",
        "operation": "aggregate",
        "sources": [{}, {}],
        "gates_applied": ["scope"],
        "claim_binding": {"mode": "record", "counts": {"total": 10, "unbound": 2}},
    }
    c = est.check_counts(ev)
    assert c["sources_total"] == 2 and c["gates_applied"] == "scope"
    assert c["claims_total"] == 10 and c["claims_unbound"] == 2
    assert est.check_counts(None)["evidence_status"] == ""


def test_assign_tasks_follows_the_schedule_and_checks_the_referent():
    chats = [
        {"participant": "P01", "created_at": t, "turns": [{"question": q}]}
        for t, q in [
            (1, "What floors does this building have?"),
            (2, "humidity in room 1.07?"),
            (3, "something unrelated"),
            (9, "my own question"),
        ]
    ]
    sched = {"P01": ["S3-1", "S2-2"]}
    est.assign_tasks(chats, sched, {"S3-1": ["1.07"], "S2-2": ["1.44"]})
    assert [c["role"] for c in chats] == ["practice", "task_1", "task_2", "own"]
    assert chats[1]["task_match"] == 1 and chats[2]["task_match"] == 0


def test_study_chats_reads_only_study_accounts_from_a_copied_database(tmp_path):
    db = tmp_path / "webui.db"
    con = sqlite3.connect(db)
    con.execute("create table user (id text, email text, role text)")
    con.execute(
        "create table chat (id text, user_id text, title text, created_at int, updated_at int, chat text)"
    )
    con.executemany(
        "insert into user values (?,?,?)",
        [("u1", "p07@study.example.com", "user"), ("u2", "someone@example.com", "user")],
    )
    ts = int(dt.datetime(2026, 10, 15, 9, tzinfo=dt.timezone.utc).timestamp())
    msgs = [
        {"role": "user", "content": "Q1", "timestamp": ts},
        {"role": "assistant", "content": "A1", "timestamp": ts + 20, "id": "a1"},
    ]
    con.executemany(
        "insert into chat values (?,?,?,?,?,?)",
        [
            ("c1", "u1", "t", ts, ts, json.dumps({"messages": msgs})),
            ("c2", "u2", "t", ts, ts, json.dumps({"messages": msgs})),
        ],
    )
    con.commit()
    con.close()
    chats = est.study_chats(db, dt.date(2026, 10, 15))
    assert [c["participant"] for c in chats] == ["P07"]
    assert chats[0]["turns"][0]["answered_at"] - chats[0]["turns"][0]["asked_at"] == 20
