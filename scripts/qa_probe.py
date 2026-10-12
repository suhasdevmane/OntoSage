#!/usr/bin/env python3
"""Ask probe questions exactly as Open WebUI does and check routing, delivery and charts.

Each question goes to /v1/chat/completions with ``stream: true`` and Open WebUI's own headers
(its chat id and the forwarded user's e-mail), after the answer, routing and compile caches are
flushed, so every ask is a true first pass. For every turn it records the lane the server says it
used (``ontosage_intent`` / ``ontosage_route``), the typed outcome fields, latency, the answer
with and without its evidence panel, and every image the answer links, FETCHED to prove it loads.

A turn is FLAGGED, with reasons, when: the request failed or came back empty; the text carries an
internal-error marker; the provider was down; the route is not one the pool accepts; a chart was
asked for and no image loaded; or an honest decline came back where an answer was expected (and
the reverse). Flags are for a human to read: they are not verdicts on answer quality.

    python scripts/qa_probe.py --sample 30 --seed 1           # 30 random questions from the pool
    python scripts/qa_probe.py --families chart,compare        # whole families
    python scripts/qa_probe.py --questions "Plot CO2 in room 5.01 today"   # ad hoc

Results: outputs/qa_probe/<run>.jsonl (+ a summary on stdout).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import requests
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PER_ASK_CACHES = ("resp_cache:*", "cache:intent:*", "cqir_compile:*")

#: Text that must never reach a reader (internal failures, raw lane names, stack traces).
ERROR_MARKERS = (
    "couldn't generate a response",
    "I processed your request, but",
    "Unknown agent",
    "Traceback (most recent call last)",
    "Internal Server Error",
    "KeyError",
    "AttributeError",
    "NoneType",
    "object has no attribute",
)
PROVIDER_MARKERS = ("language model", "not responding", "gateway unreachable")
#: Phrasings of an honest decline (the building does not hold it / must not say).
DECLINE_MARKERS = (
    "I couldn't answer",
    "couldn't answer that",
    "is not recorded",
    "isn't recorded",
    "not recorded",
    "no record",
    "does not hold",
    "doesn't hold",
    "no data",
    "No readings were found",
    "no sensor",
    "not measured",
    "can't find",
    "cannot find",
    "I can't",
    "I cannot",
    "not available",
    "I don't have",
    "There is no",
    "there is no",
    "not able to",
    "can't share",
    "cannot share",
    "won't",
)
IMG_MD = re.compile(r"!\[[^\]]*\]\(([^)\s]+)\)")
IMG_HTML = re.compile(r"<img[^>]+src=[\"']([^\"']+)[\"']", re.I)
LINK_FILE = re.compile(
    r"\]\((https?://(?:localhost|127\.0\.0\.1):8080/[^)\s]+\.(?:pdf|png|svg|csv|json|xlsx))\)", re.I
)
PANEL = re.compile(r'<details type="evidence">.*?</details>\s*', re.S)
STEPS = re.compile(r"<details>\s*<summary>Pipeline steps</summary>.*?</details>\s*", re.S)


def env(name: str, default: str = "") -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].split("#")[0].strip().strip('"').strip("'")
    return default


def flush(container: str = "redis-memory-store") -> None:
    script = " ; ".join(
        f'redis-cli --scan --pattern "{p}" | xargs -r redis-cli DEL >/dev/null'
        for p in PER_ASK_CACHES
    )
    subprocess.run(
        ["docker", "exec", container, "sh", "-c", script], capture_output=True, timeout=60
    )


def ask(
    question: str,
    base: str,
    key: str,
    email: str,
    timeout: int,
    chat_id: Optional[str] = None,
    history: Optional[List[Dict]] = None,
) -> Dict:
    chat_id = chat_id or f"probe-{uuid.uuid4().hex[:12]}"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-OpenWebUI-Chat-Id": chat_id,
        "X-OpenWebUI-User-Email": email,
        "X-OpenWebUI-User-Name": email.split("@")[0],
    }
    messages = list(history or []) + [{"role": "user", "content": question}]
    body = {"model": "ontosage", "messages": messages, "stream": True}
    t0 = time.time()
    parts: List[str] = []
    final: Dict = {}
    first_byte = None
    status = "OK"
    try:
        with requests.post(
            f"{base}/v1/chat/completions", json=body, headers=headers, timeout=timeout, stream=True
        ) as resp:
            if resp.status_code != 200:
                return {
                    "status": f"HTTP {resp.status_code}",
                    "raw": resp.text[:500],
                    "seconds": time.time() - t0,
                    "chat_id": chat_id,
                }
            for line in resp.iter_lines(decode_unicode=True):
                if first_byte is None:
                    first_byte = time.time() - t0
                if not line or not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                if delta.get("content"):
                    parts.append(delta["content"])
                for k in (
                    "ontosage_intent",
                    "ontosage_route",
                    "ontosage_llm_degraded",
                    "sources",
                    "turn_outcome",
                    "retrieval_outcome",
                    "ontosage_evidence_record",
                ):
                    if chunk.get(k) is not None:
                        final[k] = chunk[k]
    except requests.exceptions.Timeout:
        status = "TIMEOUT"
    except Exception as exc:
        status = f"ERROR {type(exc).__name__}"
    raw = "".join(parts)
    return {
        "status": status if raw.strip() or status != "OK" else "EMPTY",
        "raw": raw,
        "seconds": round(time.time() - t0, 1),
        "first_byte": round(first_byte or 0, 1),
        "chat_id": chat_id,
        **final,
    }


def fetch_image(url: str, base: str) -> Dict:
    candidates = [url]
    if url.startswith("/"):
        candidates = [f"{base}{url}", f"http://127.0.0.1:3000{url}", f"http://127.0.0.1:8080{url}"]
    else:
        for host in ("file-server-artifacts", "orchestrator", "ontosage-orchestrator"):
            if f"//{host}" in url:
                candidates.append(re.sub(r"//[^/:]+(:\d+)?", "//127.0.0.1\\1", url, count=1))
    for c in candidates:
        try:
            r = requests.get(c, timeout=30)
            ok = r.status_code == 200 and (
                r.headers.get("content-type", "").startswith("image") or len(r.content) > 1000
            )
            if ok:
                return {
                    "url": url,
                    "ok": True,
                    "fetched": c,
                    "bytes": len(r.content),
                    "type": r.headers.get("content-type", ""),
                }
        except Exception:
            continue
    return {"url": url, "ok": False, "tried": candidates}


def judge(item: Dict, res: Dict, base: str) -> Dict:
    raw = res.get("raw") or ""
    text = PANEL.sub("", STEPS.sub("", raw)).strip()
    tags = set(item.get("tags") or [])
    reasons: List[str] = []
    if res["status"] != "OK":
        reasons.append(f"status:{res['status']}")
    for m in ERROR_MARKERS:
        if m.lower() in text.lower():
            reasons.append(f"error_text:{m}")
    if res.get("ontosage_llm_degraded") or any(m in text.lower() for m in PROVIDER_MARKERS):
        reasons.append("provider")
    route = res.get("ontosage_route") or {}
    intent = route.get("intent_after_overrides") or res.get("ontosage_intent")
    expect = item.get("expect") or []
    if expect and intent not in expect:
        reasons.append(f"route:{intent} not in {expect}")
    imgs = IMG_MD.findall(raw) + IMG_HTML.findall(raw)
    images = [fetch_image(u, base) for u in imgs]
    # Files the answer links for the reader to open (a floor plan PDF): they must load too.
    for url in LINK_FILE.findall(raw):
        if url in imgs:
            continue
        try:
            r = requests.get(url, timeout=30)
            if r.status_code != 200 or len(r.content) < 500:
                reasons.append(f"link:broken {url[-60:]}")
        except Exception:
            reasons.append(f"link:unreachable {url[-60:]}")
    if "chart" in tags and not any(i["ok"] for i in images):
        reasons.append("chart:no_image" if not images else "chart:image_does_not_load")
    if images and not all(i["ok"] for i in images):
        reasons.append("image:broken")
    head = text[:400]
    declined = any(m.lower() in head.lower() for m in DECLINE_MARKERS)
    if declined and "decline" not in tags and "statement" not in tags:
        reasons.append("declined")
    if "decline" in tags and not declined and "control" not in expect:
        reasons.append("answered_where_decline_expected")
    return {
        "intent": intent,
        "final_node": route.get("final_node"),
        "overrides": route.get("overrides_applied"),
        "declined": declined,
        "images": images,
        "answer": text,
        "verdict": "FLAG" if reasons else "PASS",
        "reasons": reasons,
    }


def load_pool(path: Path) -> List[Dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for fam, items in (doc.get("families") or {}).items():
        for it in items:
            out.append({**it, "family": fam})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pool", default=str(REPO / "scripts" / "qa_probe_questions.yaml"))
    ap.add_argument("--families", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--questions", nargs="*", default=[])
    ap.add_argument(
        "--jsonl", default="", help="questions from a JSONL file with a 'question' field"
    )
    ap.add_argument("--email", default="facility03@example.com")
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--no-flush", action="store_true")
    ap.add_argument("--run", default=time.strftime("probe_%Y%m%d_%H%M%S"))
    args = ap.parse_args()

    if args.questions:
        items = [{"q": q, "expect": [], "family": "adhoc"} for q in args.questions]
    elif args.jsonl:
        items = []
        for line in Path(args.jsonl).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            items.append(
                {
                    "q": rec.get("question") or rec.get("q"),
                    "expect": rec.get("expect") or [],
                    "tags": rec.get("tags") or [],
                    "family": rec.get("family") or rec.get("role", "bank"),
                }
            )
    else:
        items = load_pool(Path(args.pool))
        if args.families:
            fams = set(args.families.split(","))
            items = [i for i in items if i["family"] in fams]
        if args.sample:
            items = random.Random(args.seed).sample(items, min(args.sample, len(items)))

    key = env("PIPELINE_API_KEY")
    out = REPO / "outputs" / "qa_probe" / f"{args.run}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    flagged = []
    for n, item in enumerate(items, 1):
        if not args.no_flush:
            flush()
        res = ask(item["q"], args.base, key, item.get("persona") or args.email, args.timeout)
        j = judge(item, res, args.base)
        row = {
            "n": n,
            "family": item["family"],
            "q": item["q"],
            "expect": item.get("expect"),
            "tags": item.get("tags"),
            **{k: v for k, v in res.items() if k != "raw"},
            **j,
        }
        with out.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        mark = "PASS" if j["verdict"] == "PASS" else "FLAG"
        print(
            f"[{n:3d}/{len(items)}] {mark} {res['seconds']:6.1f}s {str(j['intent'])[:16]:16s} {item['q'][:70]}"
            + (f"\n          -> {'; '.join(j['reasons'])}" if j["reasons"] else ""),
            flush=True,
        )
        if j["reasons"]:
            flagged.append(row)
    total = len(items)
    print(f"\n{total - len(flagged)}/{total} PASS, {len(flagged)} FLAG  ->  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
