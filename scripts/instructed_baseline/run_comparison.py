#!/usr/bin/env python3
"""Offline comparison runs (tracker E6): OntoSage (A) and the instructed assistant (B), BACK TO BACK.

For every question, in a seeded random order per question (A-then-B or B-then-A), both systems answer
the same text in the same data state, the four answer caches flushed before each. This is correction 3
of the v9 plan: a live answer and a later offline answer can see different data, so the blind
comparison uses two offline answers taken minutes apart.

    python scripts/instructed_baseline/run_comparison.py --in comparison_sample.jsonl --out comparison_runs.jsonl [--repeat 3]

Input rows: {"qid", "question", "set", "participant"(optional)}. A asks through /v1 exactly as Open WebUI
does (bearer PIPELINE_API_KEY, a unique X-Chat-Id, the forwarded e-mail of a registered offline account
with the participants' role). B runs through launch.py inside the orchestrator container. Every row is
appended as it finishes; nothing is re-run selectively.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parents[2]
OUT_DIR = REPO / "outputs" / "instructed_baseline"
CACHES = ("resp_cache:*", "cache:sparql*", "cache:intent:*", "cqir_compile:*")


def env(name: str) -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def flush() -> None:
    cmd = " ; ".join(
        f"redis-cli --scan --pattern '{p}' | xargs -r redis-cli DEL >/dev/null" for p in CACHES
    )
    subprocess.run(["docker", "exec", "redis-memory-store", "sh", "-c", cmd], capture_output=True)


def ask_ontosage(question: str, email: str, timeout: int) -> dict:
    t0 = time.monotonic()
    chat_id = f"cmp-{uuid.uuid4()}"
    try:
        r = requests.post(
            "http://127.0.0.1:8000/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {env('PIPELINE_API_KEY')}",
                "X-Chat-Id": chat_id,
                "X-OpenWebUI-User-Email": email,
                "Content-Type": "application/json",
            },
            json={
                "model": "ontobot-pipeline",
                "stream": False,
                "messages": [{"role": "user", "content": question}],
            },
            timeout=timeout,
        )
        d = r.json()
        msg = ((d.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        return {
            "answer": msg,
            "http": r.status_code,
            "seconds": round(time.monotonic() - t0, 2),
            "chat_id": chat_id,
            "route": d.get("ontosage_route"),
            "turn_outcome": d.get("turn_outcome"),
            "retrieval_outcome": d.get("retrieval_outcome"),
            "sources": d.get("sources"),
            "error": None,
        }
    except (requests.RequestException, ValueError) as exc:
        return {
            "answer": "",
            "http": None,
            "seconds": round(time.monotonic() - t0, 2),
            "chat_id": chat_id,
            "error": f"{type(exc).__name__}: {str(exc)[:200]}",
        }


def ask_baseline(row: dict, batch_file: Path, out_name: str) -> dict:
    batch_file.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    t0 = time.monotonic()
    subprocess.run(
        [
            sys.executable,
            str(Path(__file__).parent / "launch.py"),
            "--in",
            str(batch_file),
            "--out",
            out_name,
        ],
        capture_output=True,
        text=True,
    )
    lines = (
        (OUT_DIR / out_name).read_text(encoding="utf-8").splitlines()
        if (OUT_DIR / out_name).exists()
        else []
    )
    rec = json.loads(lines[-1]) if lines else {"answer": "", "error": "no output from the baseline"}
    (OUT_DIR / out_name).unlink(missing_ok=True)
    rec["wall_seconds"] = round(time.monotonic() - t0, 2)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True, help="file name under outputs/instructed_baseline/")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument(
        "--email",
        default="offline@study.example.com",
        help="registered offline account (participant role)",
    )
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()

    rows = [
        json.loads(x) for x in Path(args.inp).read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    rng = random.Random(args.seed)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / args.out
    tmp_in = OUT_DIR / "inputs" / "_cmp_one.jsonl"
    tmp_in.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for run in range(1, args.repeat + 1):
            for row in rows:
                order = ["A", "B"] if rng.random() < 0.5 else ["B", "A"]
                for system in order:
                    flush()
                    if system == "A":
                        res = ask_ontosage(row["question"], args.email, args.timeout)
                    else:
                        res = ask_baseline(row, tmp_in, "_cmp_one_out.jsonl")
                    rec = {
                        "qid": row.get("qid"),
                        "set": row.get("set", ""),
                        "participant": row.get("participant", ""),
                        "question": row["question"],
                        "run": run,
                        "system": system,
                        "order": "".join(order),
                        "answer": res.get("answer", ""),
                        "result": res,
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
                    print(
                        f"{row.get('qid')} run {run} {system}: {res.get('seconds', res.get('wall_seconds'))}s "
                        f"err={bool(res.get('error'))}",
                        flush=True,
                    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
