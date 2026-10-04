#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export every trial conversation turn, with any thumbs feedback, from Open WebUI's own store.

Phase 0.2 / 0.3 of the QA-trial plan (2026-10-02). Open WebUI keeps chats and ratings in a sqlite
database inside its container (`/app/backend/data/webui.db`: 190 chats and a `feedback` table on
the day this was written); OntoSage's Mongo `chat_history` holds one document and is not where
the transcripts are. This copies the database out (`docker cp`), pairs each user message with the
assistant message that answered it, attaches the rating a tester left on that answer, and writes
one JSONL row per turn -- the file the daily hand read and the weekly tail are drawn from.

    python scripts/export_trial_turns.py --since 2026-10-02 --out docs/phase0/trial/turns_2026-10-02.jsonl

Rows carry: chat_id, turn index, user email and Open WebUI role, question, answer (FULL -- never a
400-character window, CAVEAT-1293), timestamps, and `feedback` = {rating, reason, comment} when one
exists. The OntoSage lane and route are NOT in this store; join them from the orchestrator log by
chat id when needed (`ontosage_route` is returned on every /v1 turn).

Read-only on the source: the database is copied, never opened in place.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _copy_db(container: str) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="webui_")) / "webui.db"
    subprocess.run(
        ["docker", "cp", f"{container}:/app/backend/data/webui.db", str(tmp)],
        check=True,
        capture_output=True,
    )
    return tmp


#: The collapsible "Pipeline steps" panel Open WebUI prepends to a streamed answer; the same
#: strip `scripts/ask_questions.py` applies, so an exported answer compares with a harness one.
_PIPELINE_PANEL_RE = re.compile(
    r"<details>\s*<summary>Pipeline steps</summary>.*?</details>\s*", re.S
)

#: D11's inline evidence panel (QA-trial plan, 2026-10-02): `<details type="evidence">`,
#: appended to every figure-bearing answer. Added here in the SAME commit the panel ships,
#: because without this the weekly hand read (H7) and the figure-coverage count (I4) see the
#: answer and its own evidence panel as one blob -- the panel's "Completeness: 87%" and
#: "Sources (8):" lines would themselves satisfy a figure test, inflating any measurement of
#: how often an answer carries a figure toward the share that carries a PANEL instead.
_EVIDENCE_PANEL_RE = re.compile(
    r'<details type="evidence">\s*<summary>How I know this</summary>.*?</details>\s*', re.S
)


def _clean(answer: str) -> str:
    text = _PIPELINE_PANEL_RE.sub("", answer or "")
    text = _EVIDENCE_PANEL_RE.sub("", text)
    return text.strip()


def _messages(chat_json: dict):
    """The messages of a chat in order, from either of the two shapes Open WebUI writes."""
    msgs = chat_json.get("messages")
    if not msgs:
        hist = (chat_json.get("history") or {}).get("messages") or {}
        msgs = sorted(hist.values(), key=lambda m: m.get("timestamp") or 0)
    return msgs or []


def export(db: Path, since: dt.date, out: Path, exclude_emails: set) -> dict:
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    users = {r[0]: (r[1], r[2]) for r in cur.execute("select id, email, role from user")}
    feedback = {}
    feedback_no_message_id = 0
    # H4 (QA-trial plan, 2026-10-04): the (chat_id, message_index) COMPOSITE fallback is
    # deleted outright, not merely de-prioritised. Every feedback row observed in this
    # trial carries a message_id, so the composite half carried no recall at all and was
    # pure risk: an index-based match can silently attribute a rating to the WRONG turn
    # if a message was ever edited or regenerated, and nothing here could tell the two
    # apart. A feedback row with no message_id is now counted as UNJOINED in the summary
    # (see `unjoined_feedback` below) instead of being guessed at.
    for _id, uid, data, meta in cur.execute("select id, user_id, data, meta from feedback"):
        try:
            d, m = json.loads(data or "{}"), json.loads(meta or "{}")
        except Exception:
            continue
        mid = m.get("message_id")
        if mid:
            feedback[mid] = {
                "rating": d.get("rating"),
                "reason": d.get("reason"),
                "comment": d.get("comment"),
                "details": d.get("details"),
            }
        else:
            feedback_no_message_id += 1
    since_ts = int(dt.datetime.combine(since, dt.time.min).timestamp())
    n_rows = 0
    by_user: Counter = Counter()
    rated: Counter = Counter()
    matched_mids: set = set()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for cid, uid, title, created, updated, chat in cur.execute(
            "select id, user_id, title, created_at, updated_at, chat from chat "
            "where updated_at >= ? order by updated_at",
            (since_ts,),
        ):
            email, role = users.get(uid, ("?", "?"))
            if email in exclude_emails:
                continue
            try:
                msgs = _messages(json.loads(chat))
            except Exception:
                continue
            turn = 0
            pending = None
            for idx, m in enumerate(msgs):
                if m.get("role") == "user":
                    pending = m
                elif m.get("role") == "assistant" and pending is not None:
                    turn += 1
                    mid = m.get("id")
                    fb = feedback.get(mid)
                    if fb is not None and mid is not None:
                        matched_mids.add(mid)
                    row = {
                        "chat_id": cid,
                        "title": title,
                        "turn": turn,
                        "user": email,
                        "webui_role": role,
                        "asked_at": pending.get("timestamp"),
                        "answered_at": m.get("timestamp"),
                        "q": pending.get("content") or "",
                        "answer": _clean(m.get("content")),
                        "message_id": mid,
                        "feedback": fb,
                    }
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    n_rows += 1
                    by_user[email] += 1
                    if row["feedback"]:
                        rated[row["feedback"].get("rating")] += 1
                    pending = None
    # H4: feedback that reached no turn at all -- a message_id with no matching
    # assistant message in the window queried, plus rows with no message_id to begin
    # with. Reported rather than silently dropped, so "why did a rating not show up in
    # the export" has an answer instead of a guess.
    unjoined_by_mid = len(feedback) - len(matched_mids)
    return {
        "turns": n_rows,
        "by_user": dict(by_user),
        "ratings": dict(rated),
        "unjoined_feedback": unjoined_by_mid + feedback_no_message_id,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--since", default=dt.date.today().isoformat(), help="YYYY-MM-DD (chat updated on/after)"
    )
    ap.add_argument("--out", required=True)
    ap.add_argument("--container", default="open-webui")
    ap.add_argument(
        "--exclude", default="", help="comma-separated emails to leave out (e.g. the owner's)"
    )
    args = ap.parse_args()
    db = _copy_db(args.container)
    try:
        summary = export(
            db,
            dt.date.fromisoformat(args.since),
            Path(args.out),
            {e.strip() for e in args.exclude.split(",") if e.strip()},
        )
    finally:
        shutil.rmtree(db.parent, ignore_errors=True)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
