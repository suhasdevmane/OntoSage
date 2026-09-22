# -*- coding: utf-8 -*-
"""Do the questions that already answer still answer? (building-agnostic)

WHY THIS EXISTS. `docs/supervisor_evidence_pack` records 73 questions asked of the running system
and, for each, a hand-read verdict on whether the answer addressed the question. 52 do. That pack is
a promise, and the next change to routing or data can quietly break one of them: every failure found
in this project so far was found by asking a question, never by a unit test going red.

So the pack stops being a report and becomes a test. This re-asks the questions marked GOOD and
fails if one stops answering.

WHAT "STILL ANSWERS" MEANS. Not "produces the same words" -- readings move, and a forecast should
differ between runs. The check is that the answer is still of the same KIND: a question that was
answered is still answered, and one that was answered by an honest decline still declines. A GOOD
answer turning into "I couldn't answer that from ..." is the regression this catches; a number
changing is not.

HOW TO USE IT
    python scripts/regression_answerability.py                       # all GOOD questions
    python scripts/regression_answerability.py --only 1,5,14         # a few, by pack index
    python scripts/regression_answerability.py --baseline out.json   # write a new baseline

Nothing here names a building: the questions, the verdicts and the expectations all come from the
pack, so another building points it at its own.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

REPO = Path(__file__).resolve().parent.parent

#: Openings the system uses when it cannot ground an answer. An answer that BEGINS with one of these
#: is a decline, whatever follows. Kept as the system's own wording so a new decline phrasing shows
#: up here as a diff rather than silently counting as an answer.
_DECLINE_MARKERS = (
    "i couldn't answer that from",
    "i could not find this in",
    "i don't have that specific information",
    "i couldn't tie that question to a reading",
    "i did not find that in the records",
    "i found nothing in",
    "i have nothing grounded to answer it with",
    "could not build a clean time series",
    "no data found for your query",
    "i couldn't match that room name",
    "there is no air-pressure sensor data",
    "there is no solar irradiance measurement",
    "no readings were found for",
)

#: A refusal is a DIFFERENT thing from a decline: the system can answer and declines to, on purpose.
#: It must not be counted as a regression when a question was always meant to be refused.
_REFUSAL_MARKERS = (
    "i can't answer that",
    "never tracks individuals",
    "can't be attributed to an individual",
    "denied for every role",
)


#: Prefixes the system prepends before the reply proper. They must come off before the reply is
#: classified: "What is the air pressure in room 2.01?" answered with the access-policy preamble
#: followed by "there is no air-pressure sensor data" was read as an ANSWER, and the same question
#: answered later with the plain decline wording then looked like a regression. Same substance,
#: two classifications.
_PREAMBLES = (
    r"^pipeline steps\s*",
    r"^served at [^.]*\.\s*(?:the figures below[^.]*\.\s*)?",
)


#: Typographic characters the model and the renderer produce, mapped to the ASCII this file matches
#: on. "there is no air-pressure sensor data" failed to match its own recorded answer because the
#: text carried a NON-BREAKING hyphen (U+2011). The identical trap cost a routing rule earlier the
#: same week (BUG-864, lessons #129): a pattern written with ASCII punctuation silently stops
#: matching text that was typed, rendered or generated with the typographic form.
_PUNCT = str.maketrans({
    "‑": "-", "‐": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    "’": "'", "‘": "'", "“": '"', "”": '"', " ": " ",
})


def classify(answer: str) -> str:
    """'answered' | 'declined' | 'refused' | 'empty' -- the KIND of reply, not its content."""
    body = " ".join((answer or "").translate(_PUNCT).split()).strip().lower()
    if not body:
        return "empty"
    for pat in _PREAMBLES:
        body = re.sub(pat, "", body).strip()
    head = body[:400]
    if any(m in head for m in _REFUSAL_MARKERS):
        return "refused"
    if any(m in head for m in _DECLINE_MARKERS):
        return "declined"
    return "answered"


def pipeline_key() -> str:
    """The endpoint's bearer token, from the environment or the active/parked building's .env.

    Without it every request is 401 and every question reports as a regression — a gate that
    fails closed on its own misconfiguration is worse than no gate, so this resolves it the same
    way `scripts/ask_questions.py` does rather than asking the caller to remember.
    """
    import os

    if os.environ.get("PIPELINE_API_KEY"):
        return os.environ["PIPELINE_API_KEY"]
    for name in (".env", ".env1", ".env2", ".env3"):
        path = REPO / name
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("PIPELINE_API_KEY="):
                    return line.split("=", 1)[1].split("#")[0].strip()
    return ""


def load_pack(pack: Path) -> List[Dict[str, Any]]:
    rows = [json.loads(x) for x in (pack / "answers.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    verdicts = json.loads((pack / "review.json").read_text(encoding="utf-8")).get("verdicts", {})
    for r in rows:
        v = verdicts.get(str(r["n"]), ["UNREVIEWED", ""])
        r["verdict"], r["note"] = v[0], v[1]
        r["expected_kind"] = classify(r.get("answer", ""))
    return rows


def ask(base: str, question: str, model: str, token: str, timeout: int,
        email: str = "", chat_id: str = "") -> Dict[str, Any]:
    """One question, one fresh conversation, through the endpoint the browser uses.

    THE IDENTITY MATTERS. `/v1/chat/completions` takes the user from `X-OpenWebUI-User-Email`, and
    the role that header resolves to governs what the access policy allows. Without it the request
    runs as `readonly` and a question answered in the browser can be refused here -- which is exactly
    how a forecast that worked for a facility manager was measured as a privacy refusal.
    A fresh `X-Chat-Id` per question keeps each one a new conversation, as the pack was captured.
    """
    t0 = time.time()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if email:
        headers["X-OpenWebUI-User-Email"] = email
    if chat_id:
        headers["X-Chat-Id"] = chat_id
    try:
        r = requests.post(
            f"{base}/v1/chat/completions",
            headers=headers,
            json={"model": model, "messages": [{"role": "user", "content": question}],
                  "stream": False},
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = (((data.get("choices") or [{}])[0].get("message") or {}).get("content")) or ""
        return {"answer": text, "seconds": time.time() - t0, "error": ""}
    except Exception as exc:
        return {"answer": "", "seconds": time.time() - t0, "error": f"{type(exc).__name__}: {exc}"}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", default=str(REPO / "docs" / "supervisor_evidence_pack"))
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--model", default="ontosage")
    ap.add_argument("--token", default="", help="bearer token if the endpoint needs one")
    ap.add_argument("--email", default="facility01@example.com",
                    help="forwarded user; the ROLE comes from this and governs what is allowed")
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--only", default="", help="comma list of pack indexes")
    ap.add_argument("--include-weak", action="store_true",
                    help="also re-ask the questions that do NOT currently answer, to see if a wave fixed one")
    ap.add_argument("--out", default=str(REPO / "scripts" / "outputs"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    token = args.token or pipeline_key()
    if not token:
        print("no PIPELINE_API_KEY in the environment or any .env — every request would be 401",
              file=sys.stderr)
        return 2

    rows = load_pack(Path(args.pack))
    wanted = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    subjects = [
        r for r in rows
        if (not wanted or r["n"] in wanted)
        and (args.include_weak or r["verdict"] == "GOOD")
    ]
    if not subjects:
        print("nothing to check")
        return 0

    stamp_run = datetime.now().strftime("%H%M%S")
    print(f"re-asking {len(subjects)} question(s) from {Path(args.pack).name} "
          f"as {args.email or '(no identity - runs as readonly)'}\n")
    results, regressions, improvements = [], [], []
    for i, r in enumerate(subjects, 1):
        got = ask(args.base, r["question"], args.model, token, args.timeout,
                  email=args.email, chat_id=f"regr-{stamp_run}-{r['n']}")
        kind = classify(got["answer"]) if not got["error"] else "empty"
        # A GOOD question must keep giving the SAME KIND of reply. An answer that became a decline
        # is the regression this exists for; a decline that became an answer is an improvement.
        ok = kind == r["expected_kind"]
        status = "ok  " if ok else ("BETTER" if r["verdict"] != "GOOD" and kind == "answered" else "REGRESSED")
        if status == "REGRESSED":
            regressions.append(r["n"])
        elif status == "BETTER":
            improvements.append(r["n"])
        print(f"[{i:2d}/{len(subjects)}] #{r['n']:<3d} {status:9s} {r['expected_kind']:>8s} -> "
              f"{kind:<8s} {got['seconds']:6.1f}s  {r['question'][:52]}")
        results.append({**{k: r[k] for k in ("n", "question", "verdict", "expected_kind")},
                        "got_kind": kind, "seconds": round(got["seconds"], 1),
                        "error": got["error"], "answer": got["answer"]})

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"regression_answerability_{stamp}.json"
    path.write_text(json.dumps({"pack": args.pack, "results": results}, ensure_ascii=False, indent=2),
                    encoding="utf-8")

    print(f"\n{len(subjects) - len(regressions)} of {len(subjects)} still behave as recorded")
    if improvements:
        print(f"IMPROVED (a question that did not answer now does): {improvements}")
    if regressions:
        print(f"REGRESSED: {regressions}")
        print("A question that used to answer no longer does. Read the saved answers before merging:")
        print(f"   {path}")
        return 1
    print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
