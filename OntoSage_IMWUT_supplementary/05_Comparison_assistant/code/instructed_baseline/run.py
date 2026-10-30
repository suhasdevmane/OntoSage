"""Run the instructed assistant over a JSONL of questions, INSIDE the orchestrator container (spec §5).

Use ``launch.py`` from the host; it copies this package in and maps the files through /app/outputs.

Input rows:  {"qid": ..., "question": ..., "set": "T-LIVE|T-FRESH|T-TASK|DEV"}
Output rows: qid, run, set, question, answer, steps (action, arguments, result, sizes, timings),
             model_calls, seconds, provider_failure, error, step/time-limit flags, prompt_version,
             prompt_sha, code_sha, provider, model, started_at.

Before every question the four answer caches are flushed (resp_cache, cache:sparql, cache:intent,
cqir_compile), matching the OntoSage runs. Rows are appended as they finish, so an interrupted run
keeps every answer it produced; nothing is ever re-run selectively.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
CACHES = ("resp_cache:*", "cache:sparql*", "cache:intent:*", "cqir_compile:*")


def code_sha(prompt_path: Path) -> str:
    h = hashlib.sha256()
    for p in (HERE / "tools.py", HERE / "loop.py", HERE / "native.py", prompt_path):
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


async def flush_caches(redis_url: str) -> int:
    try:
        import redis.asyncio as aioredis
    except ImportError:  # pragma: no cover
        return -1
    r = aioredis.from_url(redis_url)
    n = 0
    try:
        for pattern in CACHES:
            keys = [k async for k in r.scan_iter(match=pattern, count=500)]
            for i in range(0, len(keys), 500):
                n += await r.delete(*keys[i : i + 500])
    finally:
        await r.aclose()
    return n


async def main_async(args: argparse.Namespace) -> int:
    from orchestrator.llm_manager import llm_manager
    from shared.config import settings

    from . import native
    from .loop import answer as json_answer
    from .tools import Toolbox

    mode = args.mode
    if mode == "auto":
        mode = "native" if getattr(settings, "MODEL_PROVIDER", "") == "hosted" else "json"
    provider = native.Provider.from_settings() if mode == "native" else None

    async def answer(question, toolbox, llm, system_prompt, today):
        if mode == "native":
            return await native.answer(question, toolbox, provider, system_prompt, today)
        return {
            **await json_answer(question, toolbox, llm, system_prompt, today),
            "mode": "json_steps",
        }

    prompt_path = HERE / "prompts" / args.prompt
    system_prompt = prompt_path.read_text(encoding="utf-8")
    meta = {
        "prompt_version": args.prompt,
        "prompt_sha": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()[:16],
        "code_sha": code_sha(prompt_path),
        "provider": getattr(settings, "MODEL_PROVIDER", ""),
        "model": (
            getattr(settings, "HOSTED_LLM_MODEL", "")
            if getattr(settings, "MODEL_PROVIDER", "") == "hosted"
            else getattr(settings, "LOCAL_LLM_MODEL", getattr(settings, "OLLAMA_MODEL", ""))
        ),
    }
    rows = [
        json.loads(x) for x in Path(args.inp).read_text(encoding="utf-8").splitlines() if x.strip()
    ]
    if args.qids:
        keep = set(args.qids.split(","))
        rows = [r for r in rows if str(r.get("qid")) in keep]
    toolbox = await Toolbox.live()
    tz = ZoneInfo(toolbox.tz)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = 0
    with out.open("a", encoding="utf-8") as fh:
        for run in range(1, args.repeat + 1):
            for r in rows:
                flushed = await flush_caches(settings.REDIS_URL) if not args.no_flush else 0
                started = datetime.now(timezone.utc).isoformat()
                res = await answer(
                    r["question"],
                    toolbox,
                    llm_manager,
                    system_prompt,
                    today=datetime.now(tz).date().isoformat(),
                )
                rec = {
                    "qid": r.get("qid"),
                    "run": run,
                    "set": r.get("set", ""),
                    "question": r["question"],
                    **res,
                    **meta,
                    "cache_keys_flushed": flushed,
                    "started_at": started,
                }
                fh.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                done += 1
                print(
                    f"[{done}] {r.get('qid')} run {run}: {res['seconds']}s steps={len(res['steps'])} "
                    f"pf={res['provider_failure']} err={bool(res['error'])}",
                    flush=True,
                )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--prompt", default="v1.txt")
    ap.add_argument("--qids", default="")
    ap.add_argument("--no-flush", action="store_true")
    ap.add_argument(
        "--mode",
        choices=("auto", "native", "json"),
        default="auto",
        help="native tool calls on an OpenAI-compatible provider (default when hosted), or JSON steps via llm_manager",
    )
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
