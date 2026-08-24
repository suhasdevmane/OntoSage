#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capture the golden baseline: every answer the system gives today (V6-T54).

Why this exists, and why it must run BEFORE any V6 code lands. V6's evidence gates are
restrictive by design, so answers WILL change. Two kinds of change look identical in an
aggregate coverage number:

* an **intended tightening** - an answer that its evidence never supported now returns an
  honest non-answer, with a named gate and a stated reason. That is the point of V6.
* a **regression** - an answer that was correct, from adequate evidence, now fails or gets
  worse, with no gate justification. That is a bug.

Without a baseline the two are indistinguishable, and the project would be steering by a
number that cannot tell success from damage. A baseline captured *after* V6 work begins has
already absorbed whatever it was meant to detect, which is why this runs first.

What is archived per question: the FULL answer (not a preview - a diff needs the whole
text), the routed intent, elapsed time, transport status, and a content hash for fast
comparison. Degraded rows are quarantined rather than recorded, because a baseline that
bakes in an LLM outage would mark every later healthy answer as a change.

Resumable by design: 1,580 questions on a local model is a multi-hour run, and a run that
cannot resume is a run that gets abandoned halfway and quietly replaced by a shorter one.

    python scripts/capture_golden_baseline.py                    # full 1,580
    python scripts/capture_golden_baseline.py --limit 40         # smoke test
    python scripts/capture_golden_baseline.py --resume <stamp>   # continue a run
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
REPO = _SCRIPT_DIR.parent
sys.path.insert(0, str(REPO))

import requests  # noqa: E402

from scripts.corpus_replay import (  # noqa: E402
    BASE_URL,
    PIPELINE_API_KEY,
    REQUEST_DELAY,
    REQUEST_TIMEOUT,
    _env_or_dotenv,
)

BANK = REPO / "tasks" / "smart_building_questions.csv"
OUT_DIR = REPO / "scripts" / "outputs" / "baseline"

FIELDS = [
    "qid",
    "source",
    "category",
    "stakeholder_role",
    "readiness_r",
    "complexity_l",
    "question",
    "intent",
    "answer",
    "answer_sha",
    "evidence_sha",
    "answer_status",
    "gates",
    "gates_advisory",
    "answer_len",
    "elapsed_s",
    "status",
]


def _login(base_url: str) -> str:
    """Session token for /chat."""
    user = _env_or_dotenv("ADMIN_USERNAME", "")
    pw = _env_or_dotenv("ADMIN_PASSWORD", "")
    r = requests.post(
        f"{base_url}/auth/login",
        headers={"Content-Type": "application/json"},
        json={"username": user, "password": pw},
        timeout=30,
    )
    r.raise_for_status()
    tok = ((r.json() or {}).get("data") or {}).get("session_token")
    if not tok:
        raise RuntimeError("login returned no session_token")
    return tok


def _ask(question: str, base_url: str, building_id: str, token: str) -> Dict[str, object]:
    """One question. Returns a row dict; status OK only when the stack was healthy.

    Uses /chat rather than /v1/chat/completions deliberately. The OpenAI-compat endpoint
    returns only the message text, while /chat also exposes ``intent``, ``sources``,
    ``plan_trace`` and — once V6-T02 lands — the ``evidence`` record. A regression gate that
    could see only the prose would miss a question silently changing lane, which is one of the
    more informative things that can go wrong.
    """
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    if building_id:
        headers["X-Building-Id"] = building_id
    body = {"message": question, "session_id": f"baseline-{uuid.uuid4().hex[:8]}"}
    time.sleep(REQUEST_DELAY)
    t0 = time.time()
    empty = {
        "answer": "",
        "intent": "",
        "evidence_sha": "",
        "answer_status": "",
        "gates": "",
        "gates_advisory": "",
        "elapsed_s": 0.0,
        "status": "",
    }
    try:
        r = requests.post(f"{base_url}/chat", headers=headers, json=body, timeout=REQUEST_TIMEOUT)
        elapsed = round(time.time() - t0, 1)
        if r.status_code != 200:
            return {**empty, "elapsed_s": elapsed, "status": f"HTTP {r.status_code}"}
        payload = r.json()
        data = payload.get("data") or payload
        answer = data.get("response") or ""
        # An HTTP 200 is not proof the system answered: on a provider refusal every agent
        # falls back to generic text that reads like a reply (BUG-177). The server declares
        # it, so quarantine the row instead of baking an outage into the baseline.
        degraded = data.get("llm_degraded")
        if degraded:
            causes = ",".join((degraded or {}).get("causes") or ["unknown"])
            return {
                **empty,
                "answer": answer,
                "elapsed_s": elapsed,
                "status": f"LLM-DEGRADED:{causes}",
            }
        # `evidence_record`, NOT `evidence`. The response carries both and they are different
        # objects: `evidence` is the older evidence DOSSIER and has no gates on it, while
        # `evidence_record` is the V6-T02 EvidenceRecord that does. Reading the wrong one left
        # `gates` and `answer_status` empty on every row of every capture ever taken, and
        # since the gate's rule is "worse + no gate fired = REGRESSION", every intended
        # tightening was unconditionally misclassified as breakage.
        ev = data.get("evidence_record")
        gates = ""
        gates_advisory = ""
        answer_status = ""
        if isinstance(ev, dict):
            applied = ev.get("gates_applied") or []
            gates = ",".join(str(g) for g in applied) if isinstance(applied, list) else ""
            answer_status = str(ev.get("status") or "")
            # gates_applied and gates_advisory are DIFFERENT questions and the impact report
            # is wrong without both. `gates_applied` names suppressions that ALREADY happened
            # (the retrieval floor removed the passage; the answer you see reflects it).
            # `gates_advisory` names verdicts that FAILED and deliberately changed nothing --
            # the only ones that answer "what would enforcing this cost?". Recording just the
            # first makes an impact report describe the past and label it the future.
            advisory = ev.get("gates_advisory") or []
            gates_advisory = (
                " | ".join(str(g) for g in advisory) if isinstance(advisory, list) else ""
            )
        # The sha answers "did the EVIDENCE behind this answer change", so the fields that
        # change on every run by construction are excluded. `retrieved_at` is literally "now";
        # hashing it would make every sha differ and say nothing -- the mistake BUG-184 was.
        ev_sha = ""
        if isinstance(ev, dict):
            _stable = {
                k: v
                for k, v in ev.items()
                if k not in ("retrieved_at", "latest_evidence_at", "served_from_cache")
            }
            ev_sha = hashlib.sha256(
                json.dumps(_stable, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
        return {
            "answer": answer,
            "intent": data.get("intent") or "",
            "evidence_sha": ev_sha,
            "answer_status": answer_status,
            "gates": gates,
            "gates_advisory": gates_advisory,
            "elapsed_s": elapsed,
            "status": "OK",
        }
    except requests.Timeout:
        return {**empty, "elapsed_s": round(time.time() - t0, 1), "status": "TIMEOUT"}
    except Exception as exc:
        return {
            **empty,
            "elapsed_s": round(time.time() - t0, 1),
            "status": f"ERROR:{str(exc)[:80]}",
        }


def _read_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        return []
    try:
        return list(csv.DictReader(path.read_text(encoding="utf-8-sig").splitlines()))
    except Exception:
        return []


def _done_qids(path: Path, retry_failed: bool = True) -> set:
    """Which questions are genuinely captured.

    A quarantined row is NOT a capture. Counting one as done made --resume a no-op on
    exactly the rows it exists to retry -- the same class of defect as BUG-176 and BUG-191:
    the harness reporting a completeness it had not achieved, in the direction that looks
    like success. `retry_failed=False` restores the literal-append behaviour for the rare
    case of wanting a run frozen exactly as it fell.
    """
    rows = _read_rows(path)
    if not retry_failed:
        return {r["qid"] for r in rows}
    return {r["qid"] for r in rows if r.get("status") == "OK"}


def _drop_rows(path: Path, qids: set) -> int:
    """Remove rows for `qids` so a retry REPLACES them rather than duplicating them.

    Written to a temp file and moved into place, so an interrupted rewrite cannot leave a
    half-truncated capture behind. Only ever asked to drop quarantined rows, which carry no
    answer text -- nothing recoverable is discarded.
    """
    rows = _read_rows(path)
    keep = [r for r in rows if r["qid"] not in qids]
    dropped = len(rows) - len(keep)
    if not dropped:
        return 0
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(keep)
    tmp.replace(path)
    return dropped


def _tally(path: Path) -> Dict[str, int]:
    """Counts over the WHOLE capture, not over this invocation.

    Tallying only what this process happened to ask would let a resume of 51 rows write
    `ok=51` over a 1,580-question run. A smaller lie than a wrong answer, but the same kind,
    and it lands in the file a supervisor reads.
    """
    out = {"ok": 0, "degraded": 0, "failed": 0}
    rows = _read_rows(path)
    for r in rows:
        s = r.get("status", "")
        if s == "OK":
            out["ok"] += 1
        elif s.startswith("LLM-DEGRADED"):
            out["degraded"] += 1
        else:
            out["failed"] += 1
    out["captured"] = len(rows)
    return out


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default=BASE_URL)
    ap.add_argument("--building", default="", help="X-Building-Id header; blank = active building")
    ap.add_argument("--limit", type=int, default=0, help="first N questions (smoke test)")
    ap.add_argument(
        "--every",
        type=int,
        default=0,
        help="take every Nth question — a deterministic stratified sample. --limit takes the "
        "FIRST N, which on a bank ordered by source means one source; --every spreads the "
        "sample across all of them and is reproducible, so two runs compare like with like.",
    )
    ap.add_argument("--source", default="", help="only this Source value")
    ap.add_argument("--resume", default="", help="timestamp of a run to continue")
    ap.add_argument(
        "--no-retry-failed",
        action="store_true",
        help="on resume, leave quarantined rows as they are (default: retry them)",
    )
    args = ap.parse_args(argv)

    rows = list(csv.DictReader(BANK.read_text(encoding="utf-8-sig").splitlines()))
    if args.source:
        rows = [r for r in rows if r.get("Source") == args.source]
    if args.every and args.every > 1:
        rows = rows[:: args.every]
    if args.limit:
        rows = rows[: args.limit]

    stamp = args.resume or datetime.now().strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = OUT_DIR / f"baseline_{stamp}.csv"
    meta_path = OUT_DIR / f"baseline_{stamp}.meta.json"

    done = _done_qids(out_csv, retry_failed=not args.no_retry_failed)
    todo = [r for r in rows if r["ID"] not in done]
    retrying = _drop_rows(out_csv, {r["ID"] for r in todo})
    print(
        f"baseline {stamp}: {len(rows)} questions, {len(done)} already captured, {len(todo)} to go"
        + (f" ({retrying} quarantined, being retried)" if retrying else "")
    )
    if not todo:
        print("nothing to do")
        return 0

    # Health first: a baseline is only valid if the stack was healthy for all of it.
    try:
        h = requests.get(f"{args.base_url}/health", timeout=20)
        if h.status_code != 200:
            print(f"REFUSING TO START: /health returned {h.status_code}")
            return 1
    except Exception as exc:
        print(f"REFUSING TO START: /health unreachable ({exc})")
        return 1

    token = _login(args.base_url)
    first = not out_csv.exists()
    ok = degraded = failed = 0
    t_start = time.time()

    with out_csv.open("a", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if first:
            w.writeheader()
        for i, q in enumerate(todo, 1):
            res = _ask(q["Question"], args.base_url, args.building, token)
            ans = str(res["answer"] or "")
            status = str(res["status"])
            if status == "OK":
                ok += 1
            elif status.startswith("LLM-DEGRADED"):
                degraded += 1
            else:
                failed += 1
            w.writerow(
                {
                    "qid": q["ID"],
                    "source": q.get("Source", ""),
                    "category": q.get("Category", ""),
                    "stakeholder_role": q.get("Stakeholder_Role", ""),
                    "readiness_r": q.get("Readiness_R", ""),
                    "complexity_l": q.get("Complexity_L", ""),
                    "question": q["Question"],
                    "intent": res["intent"],
                    "answer": ans,
                    "answer_sha": hashlib.sha256(ans.encode("utf-8")).hexdigest()[:16],
                    "evidence_sha": res.get("evidence_sha", ""),
                    "answer_status": res.get("answer_status", ""),
                    "gates": res.get("gates", ""),
                    "gates_advisory": res.get("gates_advisory", ""),
                    "answer_len": len(ans),
                    "elapsed_s": res["elapsed_s"],
                    "status": status,
                }
            )
            fh.flush()
            if i % 25 == 0 or i == len(todo):
                rate = (time.time() - t_start) / i
                eta = (len(todo) - i) * rate / 60
                print(
                    f"  {i}/{len(todo)}  ok={ok} degraded={degraded} failed={failed}  "
                    f"{rate:.1f}s/q  ETA {eta:.0f} min",
                    flush=True,
                )

    totals = _tally(out_csv)
    meta = {
        "stamp": stamp,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "questions": len(rows),
        "ok": totals["ok"],
        "degraded": totals["degraded"],
        "failed": totals["failed"],
        "this_run": {"asked": len(todo), "ok": ok, "degraded": degraded, "failed": failed},
        "base_url": args.base_url,
        "building": args.building or "(active)",
        "note": (
            "Degraded and failed rows are recorded with their status so the regression gate can "
            "exclude them. A baseline that treated an outage as an answer would mark every later "
            "healthy answer as a change."
        ),
    }
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"\nwrote {out_csv.relative_to(REPO)}")
    print(f"  this run:      ok={ok} degraded={degraded} failed={failed}")
    print(
        f"  capture total: ok={totals['ok']} degraded={totals['degraded']} "
        f"failed={totals['failed']} of {totals['captured']} rows"
    )
    if totals["degraded"] or totals["failed"]:
        print("  NOTE: re-run with --resume to retry the non-OK rows after fixing the stack.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
