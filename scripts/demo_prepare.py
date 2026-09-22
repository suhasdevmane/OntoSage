# -*- coding: utf-8 -*-
"""Get the running stack ready for a recording or a supervisor session (building-agnostic).

What it does, in order, and stops with a clear message at the first thing that would spoil a session:

1. the orchestrator answers ``/health``;
2. both answer caches are flushed, so the first ask is a real first pass (never a stale answer);
3. the model and the graph connections are WARMED with three short questions, so the first question a
   person asks is not the slow one (a cold local model can add a minute);
4. the test tickets that verification runs leave behind are counted (dry run of clear_test_reports.py),
   because they show up in answers about repeat reports.

It does NOT pre-answer the demo questions: a warmed answer cache would make a recording show
0-second answers that no viewer will ever see, and would freeze "right now" readings for up to an hour.

    python scripts/demo_prepare.py
    python scripts/demo_prepare.py --questions-file docs/demo_script_questions.txt   # also list its size
    python scripts/demo_prepare.py --test-logins facility01,admin@ontosage --since 2026-09-19
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from typing import List

import requests

REPO = Path(__file__).resolve().parent.parent
WARMUP = [
    "Show me floor 3",
    "How many rooms are on floor 2?",
    "What is the CO2 level in room 5.01 right now?",
]


def _step(n: int, text: str) -> None:
    print(f"[{n}] {text}", flush=True)


def _flush(container: str) -> bool:
    ok = True
    for pattern in ("resp_cache:*", "cache:sparql*"):
        cmd = ["docker", "exec", container, "sh", "-c",
               f'redis-cli --scan --pattern "{pattern}" | xargs -r redis-cli DEL >/dev/null']
        try:
            ok = subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0 and ok
        except Exception:
            ok = False
    return ok


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--redis-container", default="redis-memory-store")
    ap.add_argument("--questions-file", default="")
    ap.add_argument("--test-logins", default="")
    ap.add_argument("--since", default="")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    _step(1, "health")
    try:
        r = requests.get(f"{args.base}/health", timeout=8)
    except requests.RequestException as exc:
        print(f"    NOT READY: the orchestrator does not answer ({exc}). Start the stack first.")
        return 1
    if r.status_code != 200:
        print(f"    NOT READY: /health returned {r.status_code}.")
        return 1
    print("    orchestrator healthy")

    _step(2, "flush the answer caches")
    print("    flushed" if _flush(args.redis_container) else "    could not flush (is Redis up?)")

    _step(3, "warm the model and the graph (three short questions, not the demo questions)")
    t0 = time.time()
    proc = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "ask_questions.py"), "--v1", "--stream", "--show", "0",
         "--timeout", "240", *WARMUP],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    took = time.time() - t0
    if proc.returncode != 0:
        print(f"    warm-up failed ({proc.returncode}); last lines:\n" + "\n".join(proc.stdout.splitlines()[-4:]))
        return 1
    print(f"    warmed in {took:.0f} s")
    _flush(args.redis_container)  # the warm-up answers must not be served as demo answers

    if args.questions_file:
        _step(4, "the script")
        lines = [ln for ln in Path(args.questions_file).read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.startswith("#")]
        print(f"    {len(lines)} questions in {args.questions_file}; allow 15-25 minutes, three answers take 1-3 minutes")

    if args.test_logins and args.since:
        _step(5, "test tickets left by verification runs (dry run)")
        out = subprocess.run(
            [sys.executable, str(REPO / "scripts" / "clear_test_reports.py"),
             "--since", args.since, "--reporters", args.test_logins],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        print("    " + (out.stdout.strip().splitlines() or ["no output"])[0])
        print("    to remove them: add --apply to that command")

    print("\nREADY. Ask the first question now; caches are empty and the model is warm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
