# -*- coding: utf-8 -*-
"""Capture one system version's answers to a frozen compound-question set.

    python scripts/run_compound_eval.py --set eval/compound/T-REAL.jsonl --version v1

Every question is asked once, in a FRESH chat, through the endpoint Open WebUI uses (/v1),
as one fixed identity, after the three caches are flushed. The full answer and everything the
server says about how it was produced (lane, route, sources, turn outcome, plan trace,
evidence record) are written to eval/compound/results/<version>/<set name>.jsonl.

Two properties matter more than convenience:

* **It never prints question or answer text.** The v2 developer must not read the held-out
  sets (tasks/V2_COMPOUND_PLAN.md section 5). Progress lines carry the item id, seconds and the
  lane only.
* **It refuses to overwrite a capture.** A capture is evidence. Re-running into an existing
  file would silently replace the "before" with something produced later.

Building-agnostic: no building name, room or question appears here; the set file is the input.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import httpx

REPO = Path(__file__).resolve().parent.parent

#: Response-envelope fields worth keeping; anything else the server adds is kept under "extra".
_KEEP = (
    "ontosage_intent",
    "ontosage_route",
    "ontosage_plan_trace",
    "ontosage_sources",
    "ontosage_turn_outcome",
    "ontosage_retrieval_outcome",
    "ontosage_evidence_record",
    "ontosage_llm_degraded",
)


def _env_value(name: str) -> str:
    """Read one value from the active .env without printing it."""
    text = (REPO / ".env").read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(name)}=(.*)$", text, re.M)
    if not m:
        raise SystemExit(f"{name} is not set in .env (is a building active?)")
    return m.group(1).strip().strip('"')


def _flush_caches() -> None:
    """Flush the three cache prefixes so every answer is a first pass (CLAUDE.md)."""
    for pattern in ("resp_cache:*", "cache:sparql*", "cache:intent:*"):
        subprocess.run(
            [
                "docker",
                "exec",
                "redis-memory-store",
                "sh",
                "-c",
                f"redis-cli --scan --pattern '{pattern}' | xargs -r redis-cli DEL",
            ],
            check=False,
            capture_output=True,
        )


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout.strip()
    except Exception:
        return "unknown"


async def _ask(
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    item: Dict[str, Any],
    headers: Dict[str, str],
    timeout: float,
) -> Dict[str, Any]:
    async with sem:
        started = time.time()
        # The chat id and start time tie a turn to its own lines in the orchestrator log, so a
        # provider failure can be attributed to the turn it hit (added after the v1 capture,
        # which has neither; see tasks/V2_COMPOUND_PLAN.md section 5, "Provider failures").
        chat_id = f"compound-eval-{uuid.uuid4()}"
        row: Dict[str, Any] = {
            "id": item["id"],
            "chat_id": chat_id,
            "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        try:
            resp = await client.post(
                "http://127.0.0.1:8000/v1/chat/completions",
                headers={**headers, "X-Chat-Id": chat_id},
                json={
                    "model": "ontosage",
                    "messages": [{"role": "user", "content": item["question"]}],
                    "stream": False,
                },
                timeout=timeout,
            )
            data = resp.json()
            row["http_status"] = resp.status_code
            row["answer"] = ((data.get("choices") or [{}])[0].get("message") or {}).get(
                "content"
            ) or ""
            for key in _KEEP:
                row[key] = data.get(key)
            row["error"] = ""
        except Exception as exc:  # a timeout is a recorded outcome, not a crash
            row["answer"] = ""
            row["error"] = f"{type(exc).__name__}: {exc}"
        row["seconds"] = round(time.time() - started, 1)
        lane = row.get("ontosage_intent") or ("ERROR" if row["error"] else "?")
        print(f"  {item['id']}  {row['seconds']:6.1f}s  {lane}", flush=True)
        return row


async def _run(args: argparse.Namespace) -> int:
    set_path = (REPO / args.set).resolve()
    items: List[Dict[str, Any]] = [
        json.loads(line)
        for line in set_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_dir = REPO / "eval" / "compound" / "results" / args.version
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{set_path.stem}.jsonl"
    if out_path.exists() and not args.force:
        print(f"refusing to overwrite an existing capture: {out_path}", file=sys.stderr)
        return 2

    key = _env_value("PIPELINE_API_KEY")
    # An explicit --identity wins. Confirm the ROLE it resolves to from the server's own
    # "[forwarded-user] ... (role=...)" log line, never from the flag (lessons #169).
    email = args.identity or _env_value(args.identity_env)
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-OpenWebUI-User-Email": email,
    }

    if not args.no_flush:
        _flush_caches()

    meta = {
        "set": str(set_path.relative_to(REPO)),
        "version": args.version,
        "git_head": _git_head(),
        "identity": email,
        "endpoint": "/v1/chat/completions (non-streamed)",
        "concurrency": args.concurrency,
        "timeout_s": args.timeout,
        "started_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": len(items),
    }
    print(
        f"capturing {len(items)} items from {meta['set']} as {args.version} @ {meta['git_head'][:8]}"
    )

    sem = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient() as client:
        rows = await asyncio.gather(*[_ask(client, sem, it, headers, args.timeout) for it in items])

    meta["finished_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    errors = sum(1 for r in rows if r.get("error"))
    meta["errors"] = errors
    with out_path.open("w", encoding="utf-8") as fh:
        for row in sorted(rows, key=lambda r: r["id"]):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / f"{set_path.stem}.meta.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    secs = sorted(r["seconds"] for r in rows)
    p50 = secs[len(secs) // 2] if secs else 0
    p90 = secs[max(0, int(len(secs) * 0.9) - 1)] if secs else 0
    print(f"done: {len(rows)} captured, {errors} errors, p50 {p50}s, p90 {p90}s -> {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", required=True, help="a frozen set, e.g. eval/compound/T-REAL.jsonl")
    ap.add_argument("--version", required=True, help="e.g. v1 or v2")
    ap.add_argument(
        "--identity",
        default="",
        help="the email to ask as (X-OpenWebUI-User-Email); overrides --identity-env",
    )
    ap.add_argument(
        "--identity-env",
        default="OPENWEBUI_ADMIN_EMAIL",
        help="the .env key holding the identity, when --identity is not given",
    )
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--no-flush", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing capture")
    return asyncio.run(_run(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
