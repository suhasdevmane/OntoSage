#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""How often does the same question reach a different lane? (CAVEAT-400)

WHAT IT MEASURED, FIRST TIME OUT: 12 of 12 (100%) over 5 rounds. Routing does NOT vary
within a deployment.

That REFUTED the hypothesis this script was written to confirm. Lane changes had been
observed while verifying BUG-395 and BUG-399 — "any energy spikes" reaching capability and
then anomaly, "voltage fluctuation" moving to general_knowledge — and were attributed to LLM
nondeterminism. They were not. Every one of them spanned a DEPLOYMENT in which the very
inputs to classification had been changed: HBCO lay terms added, the concept cache cleared,
a building-facts TTL uploaded. Runs either side of an edit were compared and the difference
called noise.

So the script stays, with its purpose inverted: not to characterise variance, but to
establish that an observed lane change is REAL before anything is attributed to it. Run it
before and after a routing change. A single ask is not evidence either way, and this is the
cheap way to know which kind of difference you are looking at.

THE CACHE MUST BE FLUSHED BETWEEN ROUNDS
----------------------------------------
The response cache keys on the question, so asking the same thing twice returns the first
answer and its intent verbatim. Without the flush this would report perfect stability no
matter what routing did — it would measure the cache, and it would have "confirmed" the
wrong conclusion twice over. `--no-flush` exists only to demonstrate that difference.

    python scripts/measure_routing_variance.py --rounds 5
    python scripts/measure_routing_variance.py --rounds 3 --questions my_questions.txt
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess  # nosec B404 - fixed local docker command
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

import requests

REPO = Path(__file__).resolve().parent.parent
BASE = os.environ.get("ONTOSAGE_BASE", "http://127.0.0.1:8000")

#: Borderline questions — the ones whose lane was seen to move. Deliberately not a random
#: sample: a stability figure over unambiguous questions would be near 100% and say nothing.
_DEFAULT_QUESTIONS = [
    "any anomalies this week",
    "any energy spikes",
    "are there any energy spikes on floor 2 today",
    "show me energy anomalies in the last day",
    "is there a voltage fluctuation that could put our hardware at risk?",
    "are there any vibration anomalies on floor 9",
    "what is the energy use right now",
    "how many floors are there?",
    "how old is the building?",
    "which public space on floor 2 is quietest right now?",
    "what is the temperature in Room 5.04 right now?",
    "does the building have a green roof?",
]


def _flush_cache() -> None:
    try:
        subprocess.run(  # nosec B603 B607 - fixed local command
            [
                "docker",
                "exec",
                "redis-memory-store",
                "sh",
                "-c",
                "redis-cli --scan --pattern 'resp_cache:*' | xargs -r redis-cli del",
            ],
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception as exc:  # pragma: no cover - environment dependent
        print(f"[warn] cache flush failed ({exc}); the numbers below may measure the cache")


def _login(username: str, password: str) -> str:
    resp = requests.post(
        f"{BASE}/auth/login", json={"username": username, "password": password}, timeout=20
    )
    data = resp.json().get("data") or resp.json()
    token = data.get("session_token") or data.get("token") or ""
    if not token:
        raise SystemExit(f"login failed for {username}: HTTP {resp.status_code}")
    return token


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--questions", default="", help="file with one question per line")
    ap.add_argument("--user", default="bm_facility_manager")
    ap.add_argument(
        "--no-flush",
        action="store_true",
        help="skip the cache flush — measures the CACHE, not routing. For demonstration only.",
    )
    ap.add_argument("--timeout", type=int, default=220)
    args = ap.parse_args(argv)

    questions = _DEFAULT_QUESTIONS
    if args.questions:
        questions = [
            q.strip()
            for q in Path(args.questions).read_text(encoding="utf-8").splitlines()
            if q.strip()
        ]

    password = os.environ.get("BENCH_USER_PASSWORD", "BenchUser!2026-v5x")
    headers = {"Authorization": f"Bearer {_login(args.user, password)}"}

    seen: Dict[str, List[str]] = defaultdict(list)
    for rnd in range(1, args.rounds + 1):
        if not args.no_flush:
            _flush_cache()
        print(f"round {rnd}/{args.rounds}")
        for question in questions:
            try:
                resp = requests.post(
                    f"{BASE}/chat",
                    json={"message": question, "session_id": f"rv-{uuid.uuid4().hex[:8]}"},
                    headers=headers,
                    timeout=args.timeout,
                )
                intent = ((resp.json().get("data") or {}).get("intent")) or "(none)"
            except Exception as exc:
                intent = f"(error: {type(exc).__name__})"
            seen[question].append(str(intent))

    stable = 0
    print(f"\n{'lanes reached':<34} question")
    print("-" * 100)
    for question in questions:
        lanes = Counter(seen[question])
        if len(lanes) == 1:
            stable += 1
        shown = ", ".join(f"{k}x{v}" for k, v in lanes.most_common())
        flag = "  " if len(lanes) == 1 else "**"
        print(f"{flag}{shown:<32} {question[:62]}")

    total = len(questions)
    print(
        f"\nconsistent: {stable}/{total} ({100 * stable / max(total, 1):.0f}%) "
        f"over {args.rounds} rounds"
    )
    if stable < total:
        print(
            "\nRows marked ** reached more than one lane for the SAME question. A single ask "
            "of any of them is not evidence about routing; repeat it."
        )
    out = REPO / "scripts" / "outputs" / "routing_variance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"rounds": args.rounds, "stable": stable, "total": total, "observed": dict(seen)},
            indent=1,
        ),
        encoding="utf-8",
    )
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
