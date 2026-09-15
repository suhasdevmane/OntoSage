#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run the sealed Gate A set ONCE (V12-29). Procedure and rubric: docs/GATE_A_EVALUATION.md.

Refuses to run when:
  * the sealed file's SHA-256 differs from tasks/gate_a/SEALED.sha256 (the set was edited);
  * tasks/gate_a/RUN_STARTED exists (it has already been run — a second run is a rehearsal
    over questions that are no longer held out, and is not Gate A evidence).

Each question is asked twice through /v1/chat/completions with the cache flushed before every
ask. Pass 1 is the FIRST-PASS result; pass 2 is the retry. They are graded and reported
separately (lessons: a retry that succeeds is still a first-pass failure).

After the run it writes tasks/gate_a/grades.csv with one row per (question, pass) and empty
grade columns, for grading against the rubric.

    python scripts/run_gate_a.py --email <admin email>
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GATE = REPO / "tasks" / "gate_a"
SEALED = GATE / "sealed_set.jsonl"
HASH = GATE / "SEALED.sha256"
STARTED = GATE / "RUN_STARTED"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = ap.parse_args()

    if not SEALED.is_file() or not HASH.is_file():
        print("sealed set or its hash is missing — run scripts/draw_gate_a_set.py first")
        return 2
    digest = hashlib.sha256(SEALED.read_bytes()).hexdigest()
    if digest != HASH.read_text(encoding="utf-8").split()[0]:
        print("REFUSED: the sealed set does not match its recorded hash")
        return 2
    if STARTED.exists():
        print(f"REFUSED: already run ({STARTED.read_text(encoding='utf-8').strip()})")
        return 2

    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                         text=True, cwd=REPO).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--", "orchestrator", "shared"],
                                capture_output=True, text=True, cwd=REPO).stdout.strip())
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    STARTED.write_text(f"{stamp} local · HEAD {rev} · code dirty={dirty} · sha256 {digest}\n",
                       encoding="utf-8")
    out = GATE / "run.md"
    cmd = [sys.executable, str(REPO / "scripts" / "ask_questions.py"), "--v1", "--email",
           args.email, "--jsonl", str(SEALED), "--repeat", "2", "--show", "0",
           "--base-url", args.base_url, "--out", str(out)]
    rc = subprocess.run(cmd, cwd=REPO).returncode

    rows = []
    results = Path(str(out) + ".jsonl")
    if results.is_file():
        for line in results.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    with (GATE / "grades.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["question", "pass", "seconds", "harness_status", "in_scope", "grade",
                    "misrepresentation", "privacy_failure", "note"])
        for r in rows:
            w.writerow([r.get("q", ""), r.get("run", ""), round(float(r.get("secs") or 0), 1),
                        r.get("status", ""), "", "", "", "", ""])
    print(f"run finished rc={rc}; {len(rows)} asks recorded; grade tasks/gate_a/grades.csv")
    return rc


if __name__ == "__main__":
    sys.exit(main())
