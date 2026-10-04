# -*- coding: utf-8 -*-
"""The trial exporter pairs each question with its answer and its rating; the weekly draw
never re-asks a question an earlier tail or week measured (QA-trial plan, Phase 0.2/0.3/2).

Measured 2026-10-02 against the live Open WebUI store: 258 turns, one rating, which joined.
These tests build a tiny sqlite in the same shape so the pairing and the feedback join are
pinned without a container.
"""

import datetime as dt
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _db(tmp_path, with_history_shape=False):
    db = tmp_path / "webui.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        "create table user (id text, email text, role text);"
        "create table chat (id text, user_id text, title text, created_at int, updated_at int, chat text);"
        "create table feedback (id text, user_id text, data text, meta text);"
    )
    con.execute("insert into user values ('u1','occupant01@example.com','user')")
    msgs = [
        {"id": "m1", "role": "user", "content": "Is the lift working?", "timestamp": 10},
        {
            "id": "m2",
            "role": "assistant",
            "content": "<details>\n<summary>Pipeline steps</summary>\n- x\n</details>\n**All 2 lifts are operational**",
            "timestamp": 11,
        },
        {"id": "m3", "role": "user", "content": "which one did you check?", "timestamp": 12},
        {"id": "m4", "role": "assistant", "content": "Both.", "timestamp": 13},
    ]
    chat = (
        {"history": {"messages": {m["id"]: m for m in msgs}}}
        if with_history_shape
        else {"messages": msgs}
    )
    now = int(dt.datetime(2026, 10, 2, 12).timestamp())
    con.execute("insert into chat values ('c1','u1','Lift',?,?,?)", (now, now, json.dumps(chat)))
    con.execute(
        "insert into feedback values ('f1','u1',?,?)",
        (
            json.dumps({"rating": -1, "reason": "wrong", "comment": "it was broken"}),
            json.dumps({"message_id": "m4", "chat_id": "c1", "message_index": 3}),
        ),
    )
    con.commit()
    con.close()
    return db


@pytest.mark.parametrize("history_shape", [False, True])
def test_turns_are_paired_cleaned_and_rated(tmp_path, history_shape):
    mod = _load("export_trial_turns")
    out = tmp_path / "turns.jsonl"
    summary = mod.export(_db(tmp_path, history_shape), dt.date(2026, 10, 1), out, set())
    rows = [json.loads(l) for l in out.read_text(encoding="utf-8").splitlines()]
    assert summary["turns"] == 2 and len(rows) == 2
    assert rows[0]["q"] == "Is the lift working?"
    assert rows[0]["answer"].startswith("**All 2 lifts"), "the Pipeline steps panel is stripped"
    assert rows[0]["feedback"] is None
    assert rows[1]["turn"] == 2 and rows[1]["feedback"]["rating"] == -1
    assert rows[1]["feedback"]["comment"] == "it was broken"
    assert summary["ratings"] == {-1: 1}


def test_h4_a_composite_only_feedback_row_is_unjoined_not_guessed(tmp_path):
    """H4 (QA-trial plan, 2026-10-04): the (chat_id, message_index) composite fallback
    is deleted outright. A feedback row with ONLY a composite key (no message_id) must
    join to NOTHING and be counted in unjoined_feedback, never silently attached to
    whatever message happens to sit at that index -- the risk the row's own Why names."""
    mod = _load("export_trial_turns")
    db = _db(tmp_path)
    con = sqlite3.connect(str(db))
    con.execute(
        "insert into feedback values ('f2','u1',?,?)",
        (
            json.dumps({"rating": 1, "comment": "composite-only, no message_id"}),
            json.dumps({"chat_id": "c1", "message_index": 1}),  # would have matched m2
        ),
    )
    con.commit()
    con.close()
    out = tmp_path / "turns.jsonl"
    summary = mod.export(db, dt.date(2026, 10, 1), out, set())
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["feedback"] is None, "the composite-only row must not attach to m2"
    assert summary["unjoined_feedback"] == 1


def test_a_window_after_the_chat_exports_nothing(tmp_path):
    mod = _load("export_trial_turns")
    out = tmp_path / "turns.jsonl"
    assert mod.export(_db(tmp_path), dt.date(2026, 10, 3), out, set())["turns"] == 0


def test_an_excluded_email_is_left_out(tmp_path):
    mod = _load("export_trial_turns")
    out = tmp_path / "turns.jsonl"
    assert (
        mod.export(_db(tmp_path), dt.date(2026, 10, 1), out, {"occupant01@example.com"})["turns"]
        == 0
    )


def test_the_weekly_draw_excludes_every_earlier_tail_question():
    mod = _load("draw_weekly_tail")
    seen = mod._already_asked()
    tail_o = (REPO / "docs/phase0/tail_O_questions.txt").read_text(encoding="utf-8").splitlines()
    assert mod._norm(tail_o[0]) in seen
    assert mod._norm("a question nobody has asked yet") not in seen
