#!/usr/bin/env python3
"""E6 offline runs (plan 03 section 7.4), a wrapper over scripts/instructed_baseline/run_comparison.py.

    python e6_run.py --in <inputs.jsonl> --out <name.jsonl> [--repeat 3] [--systems AB|A|B] [--email ...] [--tag t1]

Uses run_comparison's own ask_ontosage() and flush() unchanged. Differences, both needed to run two processes at
once without them touching each other's files or cached answers:
  * the baseline's temporary input/output files carry --tag (run_comparison hard-codes one name);
  * --email chooses the participant-role account (the answer cache is partitioned per account for that role).
--systems A runs OntoSage only (the A-minus configuration, plan 7.2). Order per question is seeded as in
run_comparison (A-then-B or B-then-A). The four caches are flushed before every answer. Every row is appended as it
finishes; nothing is re-run selectively (plan 7.4).
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from study_paths import REPO  # noqa: E402

sys.path.insert(0, str(REPO / "scripts" / "instructed_baseline"))
import run_comparison as rc  # noqa: E402


def ask_baseline(row: dict, tag: str) -> dict:
    batch = rc.OUT_DIR / "inputs" / f"_e6_{tag}_in.jsonl"
    out_name = f"_e6_{tag}_out.jsonl"
    batch.parent.mkdir(parents=True, exist_ok=True)
    batch.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    t0 = time.monotonic()
    p = subprocess.run([sys.executable, str(REPO / "scripts" / "instructed_baseline" / "launch.py"), "--in", str(batch),
                        "--out", out_name], capture_output=True, text=True, encoding="utf-8", errors="replace")
    f = rc.OUT_DIR / out_name
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    rec = json.loads(lines[-1]) if lines else {"answer": "", "error": f"no output from the baseline: {p.stderr[-300:]}"}
    f.unlink(missing_ok=True)
    rec["wall_seconds"] = round(time.monotonic() - t0, 2)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--systems", default="AB", choices=["AB", "A", "B"])
    ap.add_argument("--seed", type=int, default=20261009)
    ap.add_argument("--email", default="offline@study.example.com")
    ap.add_argument("--tag", default="p1")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--config", default="A", help="label written on every row: A (as frozen) or A-minus")
    args = ap.parse_args()
    rows = [json.loads(x) for x in Path(args.inp).read_text(encoding="utf-8").splitlines() if x.strip()]
    rng = random.Random(args.seed)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as fh:
        for run in range(1, args.repeat + 1):
            for row in rows:
                order = ["A", "B"] if rng.random() < 0.5 else ["B", "A"]
                order = [s for s in order if s in args.systems]
                for system in order:
                    rc.flush()
                    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    res = rc.ask_ontosage(row["question"], args.email, args.timeout) if system == "A" else ask_baseline(row, args.tag)
                    rec = {**{k: row.get(k, "") for k in ("qid", "set", "participant", "form", "situation", "question")},
                           "run": run, "system": system if system == "B" else args.config, "order": "".join(order),
                           "account": args.email, "started_utc": started, "answer": res.get("answer", ""), "result": res}
                    fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                    fh.flush()
                    print(f"{time.strftime('%H:%M:%S')} {row.get('qid')} run {run} {rec['system']}: "
                          f"{res.get('seconds', res.get('wall_seconds'))}s err={bool(res.get('error'))}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
