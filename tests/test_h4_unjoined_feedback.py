"""H4 (TRIAL_TRACKER, 2026-10-06): feedback that does not join to a turn is REPORTED as
`unjoined_feedback`, never guessed onto a turn. No new behaviour: this pins the existing one.

Builds a small Open WebUI-shaped sqlite file (tables: user, chat, feedback) and runs the real
export() against it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "export_trial_turns.py"


def _load():
    spec = importlib.util.spec_from_file_location("export_trial_turns_h4", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_db(path: Path) -> None:
    con = sqlite3.connect(str(path))
    con.executescript(
        """
        create table user (id text, email text, role text);
        create table chat (id text, user_id text, title text, created_at int,
                           updated_at int, chat text);
        create table feedback (id text, user_id text, data text, meta text);
        """
    )
    con.execute("insert into user values ('u1', 'tester@example.org', 'user')")
    chat = {
        "messages": [
            {"role": "user", "content": "Is it stuffy anywhere?", "timestamp": 1},
            {"role": "assistant", "id": "m-real", "content": "Yes, floor 2.", "timestamp": 2},
        ]
    }
    now = int(dt.datetime(2026, 10, 5, 12).timestamp())
    con.execute(
        "insert into chat values ('c1', 'u1', 'Trial', ?, ?, ?)",
        (now, now, json.dumps(chat)),
    )
    # 1. joins: its message_id is a turn in the window.
    con.execute(
        "insert into feedback values ('f1', 'u1', ?, ?)",
        (json.dumps({"rating": 1}), json.dumps({"message_id": "m-real"})),
    )
    # 2. unjoined: a message_id that no turn in the window carries.
    con.execute(
        "insert into feedback values ('f2', 'u1', ?, ?)",
        (json.dumps({"rating": -1}), json.dumps({"message_id": "m-gone"})),
    )
    # 3. unjoined: no message_id at all. The retired composite (chat_id, index) fallback
    #    must NOT attach this to turn 1 -- it is counted, not guessed.
    con.execute(
        "insert into feedback values ('f3', 'u1', ?, ?)",
        (json.dumps({"rating": -1}), json.dumps({"chat_id": "c1", "message_index": 1})),
    )
    con.commit()
    con.close()


def test_unjoined_feedback_is_reported_and_not_attached_to_a_turn(tmp_path):
    mod = _load()
    db = tmp_path / "webui.db"
    _make_db(db)
    out = tmp_path / "turns.jsonl"

    summary = mod.export(db, dt.date(2026, 10, 1), out, exclude_emails=set())

    assert summary["turns"] == 1
    assert summary["unjoined_feedback"] == 2
    assert summary["ratings"] == {1: 1}
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["message_id"] == "m-real"
    assert row["feedback"]["rating"] == 1  # the one joined rating, and only that one


def test_the_summary_always_carries_the_unjoined_count(tmp_path):
    mod = _load()
    db = tmp_path / "empty.db"
    con = sqlite3.connect(str(db))
    con.executescript(
        """
        create table user (id text, email text, role text);
        create table chat (id text, user_id text, title text, created_at int,
                           updated_at int, chat text);
        create table feedback (id text, user_id text, data text, meta text);
        """
    )
    con.commit()
    con.close()
    summary = mod.export(db, dt.date(2026, 10, 1), tmp_path / "o.jsonl", exclude_emails=set())
    assert summary["unjoined_feedback"] == 0
    assert "unjoined_feedback" in summary
