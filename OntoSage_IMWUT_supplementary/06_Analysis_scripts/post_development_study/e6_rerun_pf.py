#!/usr/bin/env python3
"""Re-run each E6 provider failure ONCE, as pre-registered (plan 03 section 7: "A gateway drop-out is recorded as a
provider failure (PF) and the question is re-run once; both attempts are kept").

    python e6_rerun_pf.py runs/<file>.jsonl [...] [--email ...] [--tag pf]

A row is a provider failure when the system itself said so: result.provider_failure is true (the baseline sets it
on a gateway/HTTP error or a cut-off completion, NOT on its own "(empty answer)" at the step limit, which is the
system's answer), or OntoSage's export flag provider_failure = 1. Each PF row gets one re-run, appended to the same
file with "attempt": 2 and "rerun_of" = the original row's started_utc. Rows that already have a re-run are skipped,
so running this twice changes nothing. Nothing else is re-run.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import e6_run  # noqa: E402

rc = e6_run.rc


def is_pf(row: dict) -> bool:
    res = row.get("result") or {}
    if res.get("provider_failure") in (True, 1, "1", "true"):
        return True
    # the run harness itself failed to start the baseline (no answer was produced by either system): treated like a
    # provider failure, re-run once, both attempts kept (24 Oct; seen once, a ModuleNotFoundError in the launcher)
    if str(res.get("error") or "").startswith("no output from the baseline"):
        return True
    trace = (res.get("trace") or {}) if isinstance(res.get("trace"), dict) else {}
    return str(trace.get("provider_failure", "")) in ("1", "True", "true")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="+")
    ap.add_argument("--email", default="offline@study.example.com")
    ap.add_argument("--tag", default="pf")
    ap.add_argument("--timeout", type=int, default=420)
    args = ap.parse_args()
    for f in args.files:
        p = Path(f)
        rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
        done = {r.get("rerun_of") for r in rows if r.get("attempt") == 2}
        todo = [r for r in rows if r.get("attempt", 1) == 1 and is_pf(r) and r["started_utc"] not in done]
        print(f"{p.name}: {len(todo)} provider failure(s) to re-run once")
        with p.open("a", encoding="utf-8") as fh:
            for r in todo:
                rc.flush()
                started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                if r["system"] == "B":
                    res = e6_run.ask_baseline({k: r.get(k, "") for k in ("qid", "set", "participant", "form",
                                                                          "situation", "question")}, args.tag)
                else:
                    res = rc.ask_ontosage(r["question"], args.email, args.timeout)
                new = {**{k: r[k] for k in ("qid", "set", "participant", "form", "situation", "question", "run",
                                            "system", "order")},
                       "account": args.email if r["system"] != "B" else r.get("account", ""), "started_utc": started,
                       "attempt": 2, "rerun_of": r["started_utc"], "answer": res.get("answer", ""), "result": res}
                fh.write(json.dumps(new, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                print(f"  {r['qid']} run {r['run']} {r['system']}: re-run error={bool(res.get('error'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
