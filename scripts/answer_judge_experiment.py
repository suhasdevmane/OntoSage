# -*- coding: utf-8 -*-
"""Would a relevance judge catch the answers a reader would reject? (offline experiment)

Every unseen-question run since tail D was hand-labelled GOOD_ANSWER / GOOD_DECLINE / WEIRD. The
weird rate has sat near 40% across six sets because the tail is long: each wave fixed the answers it
was shown. This measures the one remaining general lever - a final check, by the local model, that
an answer responds to the question - against those labels, BEFORE anything is wired in.

The two numbers that decide it:
  * recall on WEIRD answers        (how many bad answers the judge would catch)
  * false-flag rate on GOOD_ANSWER (how many good answers it would wrongly replace)
A GOOD_DECLINE that is flagged costs nothing (it stays a decline).

Usage:  python scripts/answer_judge_experiment.py [--limit N] [--out FILE] [--model NAME]
Resumes from --out. Reads docs/phase0/dev_tail_{D..I}_final.jsonl and *_read.jsonl. Sends requests
only to the local Ollama (never to the orchestrator).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import requests

REPO = Path(__file__).resolve().parent.parent
PHASE0 = REPO / "docs" / "phase0"
TAILS = "DEFGHI"

SYSTEM = (
    "You audit answers given by a building-information assistant. You are NOT judging whether the "
    "facts are true (you cannot know the building). You judge only whether the answer is a sensible "
    "response to the question that was asked.\n"
    "Return exactly one label:\n"
    "ADDRESSES - the answer responds to what was asked, or honestly says the information is not held.\n"
    "OFF_TOPIC - it answers a different question, a different quantity, or lists unrelated records "
    "or statistics.\n"
    "CONTRADICTORY - it states figures or facts that conflict with each other inside the answer.\n"
    "GARBLED - a broken sentence, a raw identifier or code as the whole answer, or a fragment.\n"
    "ACTION_MISFIRE - it says it saved, filed, logged, queued or changed something the user did not "
    "ask for.\n"
    'Reply with JSON only: {"label": "...", "reason": "<12 words>"}.'
)


def load_labelled(tails: str = TAILS) -> List[Dict]:
    out: List[Dict] = []
    for tail in tails:
        answers = [
            json.loads(x)
            for x in (PHASE0 / f"dev_tail_{tail}_final.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()
        ]
        labels = [
            json.loads(x)
            for x in (PHASE0 / f"dev_tail_{tail}_final_read.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if x.strip()
        ]
        by_q = {}
        for a in answers:  # the latest run of a question wins
            by_q[a["q"].strip()] = a
        for lab in labels:
            a = by_q.get(lab["question"].strip())
            if a is None:
                continue
            out.append(
                {
                    "tail": tail,
                    "row": lab["row"],
                    "question": lab["question"],
                    "answer": a.get("answer") or "",
                    "verdict": lab["verdict"],
                    "confidence": lab["confidence"],
                    "lane": a.get("lane"),
                }
            )
    return out


def judge(base: str, model: str, question: str, answer: str, timeout: int) -> Dict:
    body = {
        "model": model,
        "stream": False,
        "think": "low",
        "format": "json",
        "options": {"temperature": 0, "num_predict": 700, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {
                "role": "user",
                "content": f"QUESTION:\n{question.strip()[:1200]}\n\nANSWER:\n{answer.strip()[:2600]}",
            },
        ],
    }
    r = requests.post(f"{base}/api/chat", json=body, timeout=timeout)
    r.raise_for_status()
    text = (r.json().get("message") or {}).get("content") or ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return {"label": "UNPARSED", "reason": text[:80]}
    return {"label": str(parsed.get("label", "UNPARSED")).upper(), "reason": str(parsed.get("reason", ""))[:120]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tails", default=TAILS, help="letters of the labelled sets to judge, e.g. J")
    ap.add_argument("--out", default=str(REPO / "docs" / "phase0" / "answer_judge_experiment.jsonl"))
    ap.add_argument("--model", default="gpt-oss:20b")
    ap.add_argument("--base", default="http://127.0.0.1:11434")
    ap.add_argument("--timeout", type=int, default=180)
    args = ap.parse_args()

    rows = load_labelled(args.tails)
    if args.limit:
        rows = rows[: args.limit]
    out = Path(args.out)
    done = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                done.add((d["tail"], d["row"]))
    print(f"{len(rows)} labelled answers, {len(done)} already judged", flush=True)
    t0 = time.time()
    with out.open("a", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            if (r["tail"], r["row"]) in done:
                continue
            try:
                j = judge(args.base, args.model, r["question"], r["answer"], args.timeout)
            except Exception as exc:  # a failed call is recorded, never guessed
                j = {"label": "ERROR", "reason": f"{type(exc).__name__}: {str(exc)[:80]}"}
            fh.write(json.dumps({**r, "judge": j}, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 10 == 0:
                print(f"  {i}/{len(rows)}  {time.time() - t0:.0f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
