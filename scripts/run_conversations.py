#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask multi-turn CONVERSATIONS and record every turn in full (Phase 1.2 of the QA-trial plan).

Every tail this project has measured was single-shot. A trial produces follow-ups -- a
clarification answered with a room number, "and yesterday?", "what about there?" -- and none of
that path had ever been exercised end to end. This runs each conversation in `--dir` (one file
per conversation, one turn per line, `#` comments allowed) through `/v1/chat/completions` with
`stream:true` and ONE chat id per file, exactly as Open WebUI does, and writes one JSONL row per
turn with the lane, the route record and the full answer.

    python scripts/run_conversations.py --dir docs/phase0/conversations --email occupant01@example.com \
        --out docs/phase0/conversations_2026-10-02_occupant.jsonl

Reuses `scripts/ask_questions.py`'s client so the identity, the streaming and the cache flush are
the same as every other measurement; confirm the role from the server's own `[forwarded-user]`
line, never from the flag (lesson #169).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from scripts.ask_questions import (  # noqa: E402
    _ask_v1_stream,
    _flush_response_cache,
    _pipeline_key,
)


def _turns(path: Path):
    return [
        l.strip()
        for l in path.read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.startswith("#")
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--no-flush", action="store_true")
    args = ap.parse_args()

    if not args.no_flush:
        _flush_response_cache("redis-memory-store")
    key = _pipeline_key()
    files = sorted(Path(args.dir).glob("*.txt"))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    n_conv = n_turn = 0
    with out.open("w", encoding="utf-8") as fh:
        for f in files:
            chat_id = f"conv-{f.stem}-{uuid.uuid4().hex[:8]}"
            history = []
            n_conv += 1
            for i, q in enumerate(_turns(f), 1):
                t0 = time.time()
                res = _ask_v1_stream(
                    history + [{"role": "user", "content": q}],
                    args.base_url,
                    key,
                    chat_id,
                    args.email,
                    args.timeout,
                )
                secs = time.time() - t0
                answer = res.get("answer") or ""
                history += [
                    {"role": "user", "content": q},
                    {"role": "assistant", "content": answer},
                ]
                row = {
                    "conversation": f.stem,
                    "turn": i,
                    "chat_id": chat_id,
                    "q": q,
                    "secs": round(secs, 1),
                    "status": res.get("status"),
                    "lane": res.get("lane"),
                    "route": res.get("route"),
                    "answer": answer,
                }
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                n_turn += 1
                print(f"[{f.stem} #{i}] {secs:5.1f}s lane={res.get('lane')} {q[:60]}")
    print(f"{n_conv} conversations, {n_turn} turns -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
