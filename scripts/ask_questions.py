#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask a short list of questions live, N times each, and record what came back.

For two jobs the regression probe is the wrong size for:

* re-asking a handful of FIXED rows to discharge an owed live check (V12-32), and
* rehearsing a demo script (DEMO-04): each question must be right on the first try, three
  times, at a latency someone can stand in front of.

WHY THE CACHE IS FLUSHED BEFORE EVERY ASK
-----------------------------------------
The response cache holds an answer for an hour. Asking the same question three times without
flushing measures one generation and two cache hits of about 0.8 s — which would report a
240-second question as fast and stable. Every repeat here is a real first pass.

Reuses the login and ask helpers from `capture_golden_baseline.py`, the same ones the probe
uses, so a question behaves here exactly as it does there.

    python scripts/ask_questions.py "Show me floor 3" "How many sensors are there?"
    python scripts/ask_questions.py --file docs/DEMO_QUESTIONS.txt --repeat 3 --out docs/DEMO_REHEARSAL.md
"""

from __future__ import annotations

import argparse
import importlib.util
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

REPO = Path(__file__).resolve().parent.parent


def _load_capture():
    spec = importlib.util.spec_from_file_location(
        "_cap", REPO / "scripts" / "capture_golden_baseline.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_cap"] = mod
    spec.loader.exec_module(mod)
    return mod


def _flush_response_cache(container: str) -> bool:
    """Delete resp_cache:* so the next ask is generated, not served from memory."""
    cmd = [
        "docker", "exec", container, "sh", "-c",
        'redis-cli --scan --pattern "resp_cache:*" | xargs -r redis-cli DEL >/dev/null',
    ]
    try:
        return subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
    except Exception:
        return False


def _questions(args) -> List[str]:
    qs = list(args.questions)
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                qs.append(line)
    if args.jsonl:
        import json

        for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
            if line.strip():
                qs.append(json.loads(line)["question"])
    return qs


def _pipeline_key() -> str:
    """PIPELINE_API_KEY from the environment, else the active or parked building's .env."""
    import os

    if os.environ.get("PIPELINE_API_KEY"):
        return os.environ["PIPELINE_API_KEY"]
    for name in (".env", ".env1"):
        path = REPO / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("PIPELINE_API_KEY="):
                    return line.split("=", 1)[1].split("#")[0].strip()
    return ""


def _ask_v1_stream(messages: List[Dict], base_url: str, key: str, chat_id: str, email: str,
                   timeout: int) -> Dict:
    """One turn with ``stream: true`` — the request Open WebUI actually sends by default.

    The streamed body carries a collapsible "Pipeline steps" panel before the answer; it is
    removed so the answer compares with a non-streamed one. ``first_byte`` records how long the
    UI showed nothing at all.
    """
    import json as _json
    import re as _re

    import requests

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "X-Chat-Id": chat_id}
    if email:
        headers["X-OpenWebUI-User-Email"] = email
    body = {"model": "ontosage", "messages": messages, "stream": True}
    t0 = time.time()
    first_byte = None
    parts: List[str] = []
    try:
        with requests.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=body,
                           headers=headers, timeout=timeout, stream=True) as resp:
            if resp.status_code != 200:
                return {"answer": resp.text[:300], "status": f"HTTP {resp.status_code}"}
            for raw in resp.iter_lines(decode_unicode=True):
                if first_byte is None:
                    first_byte = time.time() - t0
                if not raw or not raw.startswith("data: "):
                    continue
                data = raw[6:]
                if data == "[DONE]":
                    break
                try:
                    delta = _json.loads(data)["choices"][0].get("delta") or {}
                except Exception:
                    continue
                if delta.get("content"):
                    parts.append(delta["content"])
    except requests.exceptions.Timeout:
        return {"answer": "".join(parts), "status": "TIMEOUT", "first_byte": first_byte}
    except Exception as exc:
        return {"answer": "".join(parts), "status": f"ERROR {type(exc).__name__}"}
    text = _re.sub(r"<details>\s*<summary>Pipeline steps</summary>.*?</details>\s*", "",
                   "".join(parts), count=1, flags=_re.S)
    return {"answer": text, "status": "OK" if text.strip() else "EMPTY",
            "first_byte": first_byte}


def _ask_v1(messages: List[Dict], base_url: str, key: str, chat_id: str, email: str,
            timeout: int) -> Dict:
    """One turn through /v1/chat/completions, exactly as Open WebUI sends it.

    That endpoint is not the /chat one the regression probe uses: it carries conversation
    history, carry-forward pruning (BUG-525) and the forwarded identity whose role governs
    what the access policy allows. A demo given through Open WebUI is only rehearsed if it
    goes through here.
    """
    import requests

    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json",
               "X-Chat-Id": chat_id}
    if email:
        headers["X-OpenWebUI-User-Email"] = email
    body = {"model": "ontosage", "messages": messages, "stream": False}
    try:
        resp = requests.post(f"{base_url.rstrip('/')}/v1/chat/completions", json=body,
                             headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"answer": "", "status": "TIMEOUT"}
    except Exception as exc:
        return {"answer": "", "status": f"ERROR {type(exc).__name__}"}
    if resp.status_code != 200:
        return {"answer": resp.text[:300], "status": f"HTTP {resp.status_code}"}
    try:
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception:
        return {"answer": resp.text[:300], "status": "BAD_RESPONSE"}
    return {"answer": content or "", "status": "OK"}


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("questions", nargs="*")
    ap.add_argument("--file", help="one question per line; # comments allowed")
    ap.add_argument("--jsonl", help="a bank from build_stakeholder_bank.py")
    ap.add_argument("--v1", action="store_true",
                    help="ask through /v1/chat/completions, as Open WebUI does")
    ap.add_argument("--email", default="", help="forwarded Open WebUI user (role comes from it)")
    ap.add_argument("--conversation", action="store_true",
                    help="with --v1: ask every question as a follow-up in ONE chat")
    ap.add_argument("--stream", action="store_true",
                    help="with --v1: stream:true, exactly as Open WebUI sends by default")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=300, help="per-ask client timeout, seconds")
    ap.add_argument("--redis-container", default="redis-memory-store")
    ap.add_argument("--no-flush", action="store_true", help="measure cache hits deliberately")
    ap.add_argument("--out", help="write a markdown report here")
    ap.add_argument("--show", type=int, default=400, help="characters of each answer to print")
    args = ap.parse_args(argv)
    # A Windows console is cp1252 by default, and answers carry CO₂ and °C. The first run of
    # this tool died printing "₂" and lost every question after it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    qs = _questions(args)
    if not qs:
        print("no questions given")
        return 2

    token = key = None
    cap = None
    if args.v1:
        key = _pipeline_key()
        if not key:
            print("no PIPELINE_API_KEY found in the environment, .env or .env1")
            return 2
    else:
        cap = _load_capture()
        cap.REQUEST_TIMEOUT = args.timeout
        for attempt in range(1, 6):
            try:
                token = cap._login(args.base_url)
                break
            except Exception as exc:
                if attempt == 5:
                    print(f"could not authenticate: {exc}")
                    return 2
                time.sleep(5)

    import uuid as _uuid

    shared_chat = f"rehearsal-{_uuid.uuid4().hex[:8]}"
    history: List[Dict] = []
    rows: List[Dict] = []
    for q in qs:
        for i in range(1, args.repeat + 1):
            flushed = True if args.no_flush else _flush_response_cache(args.redis_container)
            t0 = time.time()
            try:
                if args.v1:
                    if args.conversation:
                        msgs, chat_id = history + [{"role": "user", "content": q}], shared_chat
                    else:
                        msgs, chat_id = [{"role": "user", "content": q}], (
                            f"rehearsal-{_uuid.uuid4().hex[:8]}"
                        )
                    asker = _ask_v1_stream if args.stream else _ask_v1
                    res = asker(msgs, args.base_url, key, chat_id, args.email, args.timeout)
                    if args.conversation and res.get("answer"):
                        history = msgs + [{"role": "assistant", "content": res["answer"]}]
                else:
                    res = cap._ask(q, args.base_url, "", token)
                answer = str(res.get("answer") or "")
                status = str(res.get("status") or "OK")
            except Exception as exc:
                answer, status = "", f"ERROR {type(exc).__name__}"
            secs = time.time() - t0
            rows.append(
                {"q": q, "run": i, "secs": secs, "status": status, "answer": answer,
                 "flushed": flushed, "first_byte": res.get("first_byte") if args.v1 else None}
            )
            if args.out:  # a long bank run must not lose every answer to one crash
                import json

                with open(f"{args.out}.jsonl", "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(rows[-1], ensure_ascii=False) + "\n")
            print(f"\n[{i}/{args.repeat}] {secs:6.1f}s  {status}  {q}")
            print("   " + answer[: args.show].replace("\n", "\n   "))

    print("\n" + "=" * 78)
    print(f"{'min':>6} {'median':>7} {'max':>6}  ok/runs  question")
    for q in qs:
        rs = [r for r in rows if r["q"] == q]
        t = [r["secs"] for r in rs]
        ok = sum(1 for r in rs if r["status"].startswith("OK") and r["answer"])
        print(f"{min(t):6.1f} {statistics.median(t):7.1f} {max(t):6.1f}  {ok}/{len(rs)}      {q[:60]}")

    if args.out:
        lines = [
            f"# Live asks — {datetime.now():%Y-%m-%d %H:%M}",
            "",
            f"{len(qs)} question(s) x {args.repeat}; response cache "
            + ("NOT flushed (cache hits measured deliberately)" if args.no_flush
               else "flushed before every ask, so every run is a real first pass") + ".",
            "",
            "| question | runs ok | min s | median s | max s |",
            "|---|---|---|---|---|",
        ]
        for q in qs:
            rs = [r for r in rows if r["q"] == q]
            t = [r["secs"] for r in rs]
            ok = sum(1 for r in rs if r["status"].startswith("OK") and r["answer"])
            lines.append(
                f"| {q} | {ok}/{len(rs)} | {min(t):.1f} | {statistics.median(t):.1f} | {max(t):.1f} |"
            )
        lines += ["", "## Answers", ""]
        for r in rows:
            lines += [f"### {r['q']} — run {r['run']} ({r['secs']:.1f} s, {r['status']})", "",
                      "```", r["answer"][:4000], "```", ""]
        Path(args.out).write_text("\n".join(lines), encoding="utf-8")
        print(f"\n[written] {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
