#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export every Paper 3 study turn, joined across the three places a turn leaves a trace.

Tracker rows D1 (study export), D2 (check counts) and D4 (provider-failure flag). One run per
collection evening, BEFORE the orchestrator log rotates (json-file, 5 x 50 MB).

The three sources and the join
  1. Open WebUI's sqlite (copied out with ``docker cp``, never opened in place): what the participant
     typed and saw, with timestamps. One row per (user message, assistant answer) pair.
  2. Postgres ``turn_memory``: the turn's intent and its bounded evidence record (status, operation,
     sources, claim-binding counts, gates applied / advisory / not evaluated). Open WebUI sends its
     chat id, and the orchestrator stores the conversation as ``owui_<chat id>:<api user>``, so a
     chat joins its rows by that id; within a chat, turns align in order, confirmed by the query
     text where it matches.
  3. The orchestrator log: the final route, the relevance gate, the claim binder and provider
     failures. Log lines carry no conversation id, so a line is assigned to the turn whose
     [asked, answered] window contains it. Study sessions run one at a time; when another
     conversation starts inside a window, the turn is flagged ``log_window_shared`` and its log
     fields must be read with care.

Provider failures (D4, CAVEAT-1409/1459) are flagged so that a gateway drop-out is never scored as
a system decline: ``provider_failure`` = 1 on the explicit dead-model wording or a gateway/breaker
log line in the window; ``provider_failure_suspected`` = 1 on the softer "... just now" fallbacks,
for a hand check.

Task assignment (questionnaire §11): a participant's chats in creation order are the practice chat,
then tasks 1..6 in their version's order (``assignment_schedule.csv``), then their own questions.
``task_match`` says whether the chat's first question names the form's referent (a room number or
floor from ``task_bank_instances.json``); a mismatch is resolved by hand and logged.

    python scripts/export_study_turns.py --since 2026-10-15 --out-dir "<folder>/exports/2026-10-15"

Writes study_turns.jsonl (full answers, with and without the evidence panel), study_turns.csv (one
row per turn, the columns the coding sheets need) and export_summary.json (counts, unjoined rows,
flags). Read-only on every source.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parents[1]
STUDY = REPO / "paper" / "phd plan" / "Suhas v9" / "11_Study_Materials"
DEFAULT_SCHEDULE = STUDY / "F_Analysis" / "outputs" / "assignment_schedule.csv"
DEFAULT_TASKS = STUDY / "C_Task_Bank_and_Keys" / "task_bank_instances.json"
STUDY_EMAIL_RE = re.compile(r"^(p\d{2})@study\.example\.com$")

_PIPELINE_PANEL_RE = re.compile(
    r"<details>\s*<summary>Pipeline steps</summary>.*?</details>\s*", re.S
)
_EVIDENCE_PANEL_RE = re.compile(r'<details type="evidence">.*?</details>\s*', re.S)

#: Explicit provider-failure wordings (circuit_breaker.py, sql_agent.py, sparql_agent.py).
PROVIDER_FAILURE_TEXT = (
    re.compile(r"language model[^.]{0,80}not responding", re.I),
    re.compile(r"wasn't able to generate an answer just now", re.I),
)
#: Softer fallbacks that are usually, but not always, a provider failure (CAVEAT-1459).
PROVIDER_SUSPECT_TEXT = re.compile(r"\bjust now\b", re.I)
#: Log markers of a provider failure (llm_manager.py, circuit_breaker.py).
PROVIDER_FAILURE_LOG = re.compile(
    r"gateway unreachable|has been unresponsive|circuit.{0,20}OPEN", re.I
)

LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),(\d{3})")
LOG_START_RE = re.compile(r"Starting workflow execution for conversation (\S+)")
LOG_ROUTE_RE = re.compile(r"Final intent for routing: (\S+)")
LOG_RELEVANCE_RE = re.compile(r"relevance gate (replaced|kept|passed|skipped)[^\n]*", re.I)
LOG_CLAIM_RE = re.compile(r"\[claim_binder\][^\n]*")


# ----------------------------------------------------------------------------------- Open WebUI
def copy_webui_db(container: str) -> Path:
    """Copy Open WebUI's sqlite out of its container; the original is never opened."""
    tmp = Path(tempfile.mkdtemp(prefix="webui_study_")) / "webui.db"
    subprocess.run(
        ["docker", "cp", f"{container}:/app/backend/data/webui.db", str(tmp)],
        check=True,
        capture_output=True,
    )
    return tmp


def _messages(chat_json: dict) -> List[dict]:
    msgs = chat_json.get("messages")
    if not msgs:
        hist = (chat_json.get("history") or {}).get("messages") or {}
        msgs = sorted(hist.values(), key=lambda m: m.get("timestamp") or 0)
    return msgs or []


def split_answer(raw: str) -> Tuple[str, str]:
    """(answer text without panels, evidence panel text or '')."""
    raw = raw or ""
    panel = _EVIDENCE_PANEL_RE.search(raw)
    text = _EVIDENCE_PANEL_RE.sub("", _PIPELINE_PANEL_RE.sub("", raw)).strip()
    return text, (panel.group(0).strip() if panel else "")


def study_chats(
    db: Path, since: dt.date, email_re: re.Pattern = STUDY_EMAIL_RE
) -> List[Dict[str, Any]]:
    """Chats of study accounts created on/after ``since``, each with its ordered turns."""
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    users = {uid: email for uid, email in cur.execute("select id, email from user")}
    since_ts = int(dt.datetime.combine(since, dt.time.min, dt.timezone.utc).timestamp())
    out = []
    for cid, uid, title, created, chat in cur.execute(
        "select id, user_id, title, created_at, chat from chat where created_at >= ? order by created_at",
        (since_ts,),
    ):
        m = email_re.match(users.get(uid, "") or "")
        if not m:
            continue
        try:
            msgs = _messages(json.loads(chat))
        except (TypeError, ValueError):
            continue
        turns, pending = [], None
        for msg in msgs:
            if msg.get("role") == "user":
                pending = msg
            elif msg.get("role") == "assistant" and pending is not None:
                text, panel = split_answer(msg.get("content") or "")
                turns.append(
                    {
                        "turn": len(turns) + 1,
                        "question": pending.get("content") or "",
                        "asked_at": pending.get("timestamp"),
                        "answered_at": msg.get("timestamp"),
                        "answer": text,
                        "evidence_panel": panel,
                        "message_id": msg.get("id"),
                    }
                )
                pending = None
        out.append(
            {
                "chat_id": cid,
                "participant": m.group(1).upper(),
                "title": title,
                "created_at": created,
                "turns": turns,
            }
        )
    con.close()
    return out


# ---------------------------------------------------------------------------------- turn_memory
def fetch_turn_memory(
    chat_ids: Iterable[str], container: str = "postgres-user-data"
) -> Dict[str, List[dict]]:
    """turn_memory rows per Open WebUI chat id (conversation_id = owui_<chat id>:<api user>)."""
    ids = sorted({c for c in chat_ids if re.fullmatch(r"[0-9a-fA-F-]{8,64}", c or "")})
    if not ids:
        return {}
    pattern = "^owui_(" + "|".join(ids) + "):"
    sql = (
        "select coalesce(json_agg(t order by t.conversation_id, t.turn_index), '[]'::json) from ("
        "select conversation_id, user_id, turn_index, user_query, intent, evidence, created_at "
        f"from turn_memory where conversation_id ~ '{pattern}' and user_query not like '### Task:%') t;"
    )
    res = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$0"',
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    rows = json.loads(res.stdout.strip() or "[]")
    by_chat: Dict[str, List[dict]] = defaultdict(list)
    for r in rows:
        chat = r["conversation_id"][len("owui_") :].split(":", 1)[0]
        by_chat[chat].append(r)
    return dict(by_chat)


def fetch_turn_memory_by_user(
    usernames: Iterable[str], since: dt.date, container: str = "postgres-user-data"
) -> Dict[str, List[dict]]:
    """turn_memory rows per study username since a date: the fallback join when a chat's id never
    reached the orchestrator (BUG-1484: Open WebUI's chat-id header went unread before 10 Oct)."""
    names = sorted({u for u in usernames if re.fullmatch(r"study_p\d{2}", u or "")})
    if not names:
        return {}
    sql = (
        "select coalesce(json_agg(t order by t.created_at), '[]'::json) from ("
        "select conversation_id, user_id, turn_index, user_query, intent, evidence, created_at "
        f"from turn_memory where user_id in ({','.join(repr(n) for n in names)}) "
        f"and created_at >= '{since.isoformat()}' and user_query not like '### Task:%') t;"
    )
    res = subprocess.run(
        [
            "docker",
            "exec",
            container,
            "sh",
            "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$0"',
            sql,
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    by_user: Dict[str, List[dict]] = defaultdict(list)
    for r in json.loads(res.stdout.strip() or "[]"):
        by_user[r["user_id"]].append(r)
    return dict(by_user)


def rows_in_window(
    rows: List[dict], start: dt.datetime, end: dt.datetime, question: str
) -> List[dict]:
    """The user's rows stored inside a turn's [asked, answered + 60 s] window whose query resembles it."""
    out = []
    for r in rows:
        try:
            ts = dt.datetime.fromisoformat(str(r["created_at"])).replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
        if (
            start <= ts <= end + dt.timedelta(seconds=60)
            and _sim(question, r.get("user_query")) >= 0.6
        ):
            out.append(r)
    return out


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _how(s: float, fallback: str) -> str:
    return "text" if s >= 0.95 else "fuzzy" if s >= 0.6 else fallback


def align(turns: List[dict], rows: List[dict], min_sim: float = 0.25) -> List[Optional[dict]]:
    """For each Open WebUI turn, the turn_memory row it corresponds to (or None).

    Equal counts (the normal case: one stored row per answered turn) align by order. Unequal counts
    (a turn failed before it was stored, or a message was regenerated) take the order-preserving
    alignment with the largest total query similarity, accepting a pair only above ``min_sim``. A
    co-reference rewrite changes the stored text, which is why order, not text, is primary.
    ``aligned_by`` records the evidence for each pair: text / fuzzy / order / dp."""
    rows = sorted(rows, key=lambda r: r.get("turn_index") or 0)
    if not rows:
        return [None] * len(turns)
    if len(rows) == len(turns):
        return [
            {**r, "aligned_by": _how(_sim(t["question"], r.get("user_query")), "order")}
            for t, r in zip(turns, rows)
        ]
    n, m = len(turns), len(rows)
    sim = [
        [_sim(turns[i]["question"], rows[j].get("user_query")) for j in range(m)] for i in range(n)
    ]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(m - 1, -1, -1):
            take = sim[i][j] + best[i + 1][j + 1] if sim[i][j] >= min_sim else -1.0
            best[i][j] = max(take, best[i + 1][j], best[i][j + 1])
    out: List[Optional[dict]] = [None] * n
    i = j = 0
    while i < n and j < m:
        if sim[i][j] >= min_sim and best[i][j] == sim[i][j] + best[i + 1][j + 1]:
            out[i] = {**rows[j], "aligned_by": _how(sim[i][j], "dp")}
            i, j = i + 1, j + 1
        elif best[i][j] == best[i + 1][j]:
            i += 1
        else:
            j += 1
    return out


# ------------------------------------------------------------------------------------------ log
def parse_log(lines: Iterable[str]) -> List[Tuple[dt.datetime, str]]:
    """(UTC timestamp, line) for every timestamped orchestrator log line."""
    out = []
    for line in lines:
        m = LOG_TS_RE.match(line)
        if m:
            ts = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S").replace(
                microsecond=int(m.group(2)) * 1000, tzinfo=dt.timezone.utc
            )
            out.append((ts, line.rstrip("\n")))
    return out


def window_events(
    log: List[Tuple[dt.datetime, str]],
    start: dt.datetime,
    end: dt.datetime,
    conversation_hint: str = "",
) -> Dict[str, Any]:
    """What the log says happened between a question and its answer."""
    lines = [ln for ts, ln in log if start <= ts <= end]
    starts = [m.group(1) for ln in lines for m in [LOG_START_RE.search(ln)] if m]
    others = [s for s in starts if conversation_hint and conversation_hint not in s]
    routes = [m.group(1) for ln in lines for m in [LOG_ROUTE_RE.search(ln)] if m]
    return {
        "log_lines": len(lines),
        "route_final": routes[-1] if routes else "",
        "relevance_gate": [
            m.group(0)[:200] for ln in lines for m in [LOG_RELEVANCE_RE.search(ln)] if m
        ],
        "claim_binder": [m.group(0)[:200] for ln in lines for m in [LOG_CLAIM_RE.search(ln)] if m],
        "provider_log": [ln[:200] for ln in lines if PROVIDER_FAILURE_LOG.search(ln)],
        "log_window_shared": int(bool(others)),
    }


def read_orchestrator_log(container: str, since: dt.datetime) -> List[str]:
    res = subprocess.run(
        ["docker", "logs", "--since", since.strftime("%Y-%m-%dT%H:%M:%SZ"), container],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return (res.stdout + "\n" + res.stderr).splitlines()


# ------------------------------------------------------------------------------- derived fields
def provider_flags(answer: str, provider_log: List[str]) -> Tuple[int, int]:
    """(provider_failure, provider_failure_suspected)."""
    hard = any(p.search(answer or "") for p in PROVIDER_FAILURE_TEXT) or bool(provider_log)
    soft = (not hard) and bool(PROVIDER_SUSPECT_TEXT.search(answer or ""))
    return int(hard), int(soft)


def check_counts(evidence: Optional[dict]) -> Dict[str, Any]:
    """D2: which evidential checks acted on the turn, from its stored evidence record."""
    ev = evidence or {}
    cb = ev.get("claim_binding") or {}
    counts = cb.get("counts") or {}
    return {
        "evidence_status": ev.get("status", ""),
        "evidence_operation": ev.get("operation", ""),
        "sources_total": ev.get("sources_total", len(ev.get("sources") or [])),
        "gates_applied": ";".join(map(str, ev.get("gates_applied") or [])),
        "gates_advisory": ";".join(map(str, ev.get("gates_advisory") or [])),
        "gates_not_evaluated": ";".join(map(str, ev.get("gates_not_evaluated") or [])),
        "omitted_criteria": ";".join(map(str, ev.get("omitted_criteria") or [])),
        "claim_binding_mode": cb.get("mode", ""),
        "claims_total": counts.get("total", ""),
        "claims_unbound": counts.get("unbound", ""),
    }


def assign_tasks(
    chats: List[dict], schedule: Dict[str, List[str]], referents: Dict[str, List[str]]
) -> None:
    """Label each chat practice / task_k (form) / own, in creation order per participant."""
    by_p: Dict[str, List[dict]] = defaultdict(list)
    for c in chats:
        by_p[c["participant"]].append(c)
    for p, cs in by_p.items():
        forms = schedule.get(p, [])
        for i, c in enumerate(sorted(cs, key=lambda x: x["created_at"])):
            c["chat_seq"] = i + 1
            if i == 0:
                c["role"], c["form"] = "practice", ""
            elif i <= len(forms):
                c["role"], c["form"] = f"task_{i}", forms[i - 1]
            else:
                c["role"], c["form"] = "own", ""
            first_q = c["turns"][0]["question"] if c["turns"] else ""
            refs = referents.get(c["form"], [])
            c["task_match"] = "" if not refs else int(any(r in first_q for r in refs))


def load_schedule(path: Path) -> Dict[str, List[str]]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {
            r["participant_code"]: [r[k] for k in sorted(r) if k.startswith("task_")]
            for r in csv.DictReader(fh)
        }


def load_referents(path: Path) -> Dict[str, List[str]]:
    """Room numbers / floor numbers a form's goal card names, for the task_match check."""
    if not path.is_file():
        return {}
    out = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["forms"]:
        p = f.get("params", {})
        refs = [p["room"]] if "room" in p else list(p.get("rooms", []))
        refs += [f"loor {x}" for x in p.get("floors", [])]
        # A form with no room or floor carries its own words; none is written here, because this
        # repository is public and the study's tasks must not be.
        refs += list(p.get("match_terms", []))
        out[f["form"]] = refs
    return out


# ----------------------------------------------------------------------------------------- main
CSV_FIELDS = [
    "participant",
    "chat_seq",
    "role",
    "form",
    "task_match",
    "chat_id",
    "turn",
    "asked_at_utc",
    "answered_at_utc",
    "latency_s",
    "question",
    "answer_chars",
    "evidence_panel_present",
    "intent",
    "route_final",
    "aligned_by",
    "evidence_status",
    "evidence_operation",
    "sources_total",
    "gates_applied",
    "gates_advisory",
    "gates_not_evaluated",
    "omitted_criteria",
    "claim_binding_mode",
    "claims_total",
    "claims_unbound",
    "relevance_gate",
    "provider_failure",
    "provider_failure_suspected",
    "log_window_shared",
    "message_id",
]


def _iso(ts: Optional[float]) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat() if ts else ""


def _stored_at(row: Optional[dict]) -> Optional[dt.datetime]:
    """When turn_memory stored a turn (UTC): the end of the turn as the system saw it."""
    if not row or not row.get("created_at"):
        return None
    try:
        return dt.datetime.fromisoformat(str(row["created_at"])).replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def build_rows(
    chats: List[dict],
    tm: Dict[str, List[dict]],
    log: List[Tuple[dt.datetime, str]],
    tm_by_user: Optional[Dict[str, List[dict]]] = None,
) -> List[dict]:
    rows = []
    tm_by_user = tm_by_user or {}
    for c in chats:
        aligned = align(c["turns"], tm.get(c["chat_id"], []))
        if not any(aligned):
            # fallback: the participant's rows in each turn's time window (BUG-1484 era chats)
            user_rows = tm_by_user.get(f"study_{c['participant'].lower()}", [])
            aligned = []
            for t in c["turns"]:
                s = dt.datetime.fromtimestamp(t["asked_at"] or 0, dt.timezone.utc)
                e = dt.datetime.fromtimestamp(
                    t["answered_at"] or t["asked_at"] or 0, dt.timezone.utc
                )
                hits = rows_in_window(user_rows, s, e, t["question"])
                aligned.append({**hits[0], "aligned_by": "user_time"} if len(hits) == 1 else None)
        for t, r in zip(c["turns"], aligned):
            start = dt.datetime.fromtimestamp(t["asked_at"] or 0, dt.timezone.utc)
            # Open WebUI stamps the assistant message when it creates the placeholder (the same
            # second as the question), so the END of a turn comes from when turn_memory stored it;
            # without a joined row the window is the per-turn time limit.
            stored = _stored_at(r)
            end = (
                (stored + dt.timedelta(seconds=2)) if stored else start + dt.timedelta(seconds=300)
            )
            t = {**t, "latency_s": round((stored - start).total_seconds(), 1) if stored else ""}
            ev = window_events(log, start, end, conversation_hint=c["chat_id"])
            pf, ps = provider_flags(t["answer"], ev["provider_log"])
            evidence = (r or {}).get("evidence")
            if isinstance(evidence, str):
                try:
                    evidence = json.loads(evidence)
                except ValueError:
                    evidence = None
            rows.append(
                {
                    "participant": c["participant"],
                    "chat_seq": c.get("chat_seq", ""),
                    "role": c.get("role", ""),
                    "form": c.get("form", ""),
                    "task_match": c.get("task_match", ""),
                    "chat_id": c["chat_id"],
                    "turn": t["turn"],
                    "asked_at_utc": _iso(t["asked_at"]),
                    "answered_at_utc": _iso(t["answered_at"]),
                    "latency_s": t["latency_s"],
                    "question": t["question"],
                    "answer": t["answer"],
                    "evidence_panel": t["evidence_panel"],
                    "answer_chars": len(t["answer"]),
                    "evidence_panel_present": int(bool(t["evidence_panel"])),
                    "intent": (r or {}).get("intent", ""),
                    "route_final": ev["route_final"],
                    "aligned_by": (r or {}).get("aligned_by", "UNJOINED"),
                    **check_counts(evidence),
                    "relevance_gate": " | ".join(ev["relevance_gate"]),
                    "provider_failure": pf,
                    "provider_failure_suspected": ps,
                    "log_window_shared": ev["log_window_shared"],
                    "message_id": t["message_id"],
                    "evidence_record": evidence,
                    "claim_binder_log": ev["claim_binder"],
                    "provider_log": ev["provider_log"],
                }
            )
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--since", default=dt.date.today().isoformat(), help="chats created on/after (UTC date)"
    )
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--webui-container", default="open-webui")
    ap.add_argument("--orchestrator-container", default="ontosage-orchestrator")
    ap.add_argument("--schedule", default=str(DEFAULT_SCHEDULE))
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS))
    args = ap.parse_args()

    db = copy_webui_db(args.webui_container)
    try:
        chats = study_chats(db, dt.date.fromisoformat(args.since))
    finally:
        shutil.rmtree(db.parent, ignore_errors=True)
    assign_tasks(chats, load_schedule(Path(args.schedule)), load_referents(Path(args.tasks)))
    tm = fetch_turn_memory(c["chat_id"] for c in chats)
    tm_by_user = fetch_turn_memory_by_user(
        (f"study_{c['participant'].lower()}" for c in chats), dt.date.fromisoformat(args.since)
    )
    since_dt = dt.datetime.combine(dt.date.fromisoformat(args.since), dt.time.min, dt.timezone.utc)
    log = parse_log(read_orchestrator_log(args.orchestrator_container, since_dt))
    rows = build_rows(chats, tm, log, tm_by_user)

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with (out / "study_turns.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    with (out / "study_turns.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=CSV_FIELDS,
            quoting=csv.QUOTE_ALL,
            lineterminator="\n",
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)
    log_first = log[0][0].isoformat() if log else ""
    summary = {
        "since": args.since,
        "chats": len(chats),
        "turns": len(rows),
        "participants": sorted({c["participant"] for c in chats}),
        "turns_unjoined_to_turn_memory": sum(1 for r in rows if r["aligned_by"] == "UNJOINED"),
        "aligned_by": dict(Counter(r["aligned_by"] for r in rows)),
        "task_mismatch_chats": sorted(
            {(r["participant"], r["chat_seq"]) for r in rows if r["task_match"] == 0}
        ),
        "provider_failure": sum(r["provider_failure"] for r in rows),
        "provider_failure_suspected": sum(r["provider_failure_suspected"] for r in rows),
        "log_window_shared": sum(r["log_window_shared"] for r in rows),
        "evidence_panel_present": sum(r["evidence_panel_present"] for r in rows),
        "orchestrator_log_starts_at": log_first,
        # the log must reach back to the FIRST question exported, or route/gate/provider fields
        # for the early turns are missing (json-file rotation, or a container restart)
        "log_covers_all_turns": bool(log)
        and all(r["asked_at_utc"] >= log_first for r in rows if r["asked_at_utc"]),
    }
    (out / "export_summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
