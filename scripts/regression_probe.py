#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ask the live system the questions we have already proved it can answer.

WHY THIS EXISTS
---------------
The unit suite protects the CODE. It cannot tell you that "who do I contact about a broken
door closer?" still returns DEP-01 and a 24-hour target, because that answer depends on the
graph, the registers, five routing components and the model — none of which a unit test
exercises together.

Every fix in this project's history that broke something else broke it exactly here: a
routing guard added for one question shape silently took another shape with it. BUG-431's
first fix is the clearest case — it corrected "how many CO2 sensors" and, in doing so,
started answering it with the building-wide total instead. A unit test would not have
noticed; this would.

WHAT IT CHECKS
--------------
Each case names a question and a `expect` marker that MUST appear in the answer — a figure,
a record id, a department code. Markers are facts the register holds, not phrasings, so a
reworded answer still passes and a wrong FIGURE fails. `forbid` catches known-wrong answers
that a regression would bring back.

`expect_sparql` computes the expected figure FROM THE GRAPH at probe time, for quantities
that move on their own. A number written down once decays quietly and then fails on a day
nobody chose — the overdue-calibration count went 194 -> 201 -> 206 while the system stayed
correct throughout.

`expect_intent` / `forbid_intent` assert the LANE instead of the words, for cases where
that is the whole point. A question answered from the wrong lane comes back fluent and
plausible — "how many work orders are open?" answered from the building-hours document
reads perfectly — so no marker over the text can tell the lanes apart.

    python scripts/regression_probe.py              # all cases
    python scripts/regression_probe.py --only registers
    python scripts/regression_probe.py --baseline   # write the current answers as the record
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CASES_PATH = REPO / "scripts" / "regression_cases.json"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _matches(answer: str, marker: str) -> bool:
    """Case-insensitive, and tolerant of the separators a model renders numbers with.

    A model writes 2,728 or 2728 or 2 728 for the same figure, and an en-dash where the
    register has a hyphen. Failing a regression check on typography would train whoever
    runs this to ignore it, which is worse than not having it.
    """
    a = answer.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    a = a.replace("’", "'").replace(" ", " ").replace("\xa0", " ")
    m = marker.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    return m in a


def _scalar_from_graph(query: str, base_url: str, repo: str) -> Optional[str]:
    """The single value a SPARQL query returns, as the string an answer would print.

    Used by `expect_sparql` so a case about a moving quantity checks itself against the
    graph instead of against a number somebody wrote down once (see the note at the call
    site). Returns None on any failure — the caller turns that into a FAILING expectation
    rather than a skipped one, because a check that could not run must never report green.

    Integers come back without a decimal tail: SPARQL COUNT yields "206", but a typed
    total can arrive as "206.0", and an answer says "206".
    """
    try:
        resp = requests.post(
            f"{base_url.rstrip('/')}/repositories/{repo}",
            data=query.encode("utf-8"),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"  [expect_sparql] HTTP {resp.status_code} from GraphDB")
            return None
        bindings = resp.json().get("results", {}).get("bindings", [])
        if not bindings:
            print("  [expect_sparql] query returned no rows")
            return None
        row = bindings[0]
        value = row[next(iter(row))]["value"]
    except Exception as exc:
        print(f"  [expect_sparql] {type(exc).__name__}: {exc}")
        return None
    try:
        f = float(value)
        if f == int(f):
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return str(value)


def _active_building(base_url: str) -> str:
    """The building the RUNNING orchestrator is serving, from /health.

    Read from the process, never from `input/env.building`, because the two diverge:
    compose tags an image per building and neither `restart` nor a plain `up -d` rebuilds
    one that already exists, so a renamed input directory does not change what is
    answering (BUG-343). A probe that trusted the filesystem would assert bldg1's room
    numbers against bldg3's graph and report every mismatch as a regression.

    Returns "" when the field is absent -- an older image, in which case the caller runs
    every case and says so rather than silently skipping the building-specific ones.
    """
    try:
        resp = requests.get(f"{base_url.rstrip('/')}/health", timeout=30)
        return str(((resp.json() or {}).get("data") or {}).get("building_id") or "")
    except Exception:
        return ""


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--only", default="", help="run only cases in this group")
    ap.add_argument(
        "--building",
        default="",
        help="building id these cases are valid for; default: read from /health",
    )
    ap.add_argument(
        "--graphdb-url",
        default="http://localhost:7200",
        help="GraphDB base URL, for cases whose expectation is computed live",
    )
    ap.add_argument("--graphdb-repo", default="bldg")
    ap.add_argument("--out", default=str(REPO / "docs" / "REGRESSION_PROBE.md"))
    args = ap.parse_args(argv)

    cases: List[Dict[str, Any]] = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if c.get("group") == args.only]

    # ── which cases apply to the building that is actually running ──────────────
    #
    # A case naming a `building` asserts facts only that building holds -- a department
    # code, a room id, an asset label. Running it against another building fails on
    # every marker and says nothing about portability; SKIPPING it silently is worse,
    # because the run then reports a pass rate over an unstated denominator. So the
    # skipped set is counted and printed.
    active = args.building or _active_building(args.base_url)
    skipped = [c for c in cases if c.get("building") and active and c["building"] != active]
    if active:
        cases = [c for c in cases if not c.get("building") or c["building"] == active]
    if not cases:
        print("no cases selected")
        return 2

    cap = _load("_cap", "scripts/capture_golden_baseline.py")
    # RETRY THE LOGIN. The first request after a container restart routinely exceeds the
    # 30-second read timeout while the app finishes warming, and a probe that dies at the
    # door reports nothing about the system — which is indistinguishable, in a log, from a
    # probe that found nothing wrong.
    token = None
    for attempt in range(1, 6):
        try:
            token = cap._login(args.base_url)
            break
        except Exception as exc:
            if attempt == 5:
                print(f"could not authenticate after 5 attempts: {exc}")
                return 2
            print(f"  login attempt {attempt} failed ({type(exc).__name__}), retrying")
            time.sleep(20)
    provider, model = cap._active_model(args.base_url, token)
    print(
        f"regression probe: {len(cases)} cases against {provider}/{model} "
        f"· building {active or '(not reported by /health — running every case)'}"
    )
    if skipped:
        groups = sorted({f"{c.get('group','')}/{c.get('building')}" for c in skipped})
        print(f"  {len(skipped)} case(s) skipped as not applicable here: {', '.join(groups)}")
    # EVERY CASE IS ASKED EXACTLY ONCE. There is no per-case retry, deliberately: a run
    # reported as "49/50, the failure passed on retry" has folded a first-pass failure
    # into a success total, and first-pass behaviour is what a user experiences. The
    # login above retries because a probe that dies at the door measures nothing; that
    # is transport, not an answer.
    print("  each case asked once — no retries; a failure here is a FIRST-PASS failure\n")

    rows, failed = [], 0
    t0 = time.time()
    for i, case in enumerate(cases, 1):
        # A PER-CASE TIMEOUT, because some lanes are legitimately slow.
        #
        # "Give me a report on energy use yesterday" routes to the report lane, which
        # GENERATES A DOCUMENT -- its SQL returns one row per query and it still takes
        # minutes. Timing that out reports a working feature as broken, and a probe that
        # cries wolf is one nobody reads. Raising the default for every case would instead
        # hide a genuine hang, so the allowance is stated on the case that needs it.
        _prev_timeout = cap.REQUEST_TIMEOUT
        if case.get("timeout_s"):
            cap.REQUEST_TIMEOUT = int(case["timeout_s"])
        try:
            res = cap._ask(case["question"], args.base_url, "", token)
        finally:
            cap.REQUEST_TIMEOUT = _prev_timeout
        answer = str(res.get("answer") or "")
        # ── a marker that does not rot ──────────────────────────────────────────
        #
        # `expect_sparql` computes the expected figure FROM THE GRAPH at probe time and
        # requires it in the answer.
        #
        # "How many sensors are overdue for calibration?" was pinned at 201, re-baselined
        # from an earlier 194. It failed on 2026-09-08 because the true answer had become
        # 206: `ontosage:calibrationDueOn` dates pass as real time advances, so five more
        # sensors fell overdue and the system reported them correctly. Nothing was broken
        # except the expectation.
        #
        # A frozen number for a quantity that moves with the calendar is a scheduled false
        # alarm — it decays silently and fires on a day nobody chose. Weakening the case to
        # "contains a number" would fix the noise and lose the point, which is to catch a
        # WRONG figure. Computing the truth alongside the question keeps both.
        expected_live: List[str] = []
        for _q in case.get("expect_sparql", []) or []:
            _v = _scalar_from_graph(_q, args.graphdb_url, args.graphdb_repo)
            if _v is None:
                # An unanswerable expectation must FAIL, never silently pass: a probe that
                # skips the check it could not run reports green for an unchecked case.
                expected_live.append("<graph query failed — expectation not evaluated>")
            else:
                expected_live.append(_v)
        missing = [
            m for m in list(case.get("expect", [])) + expected_live if not _matches(answer, m)
        ]
        present = [f for f in case.get("forbid", []) if _matches(answer, f)]
        # `expect_any` is satisfied by ANY ONE of its markers.
        #
        # The same fact is rendered differently between runs at temperature: the overdue
        # fume cupboard comes back as "FC-301", as "HZ-003" and as "Level 3 fume cupboard",
        # all correct. A marker list requiring every spelling fails on style, and a probe
        # that cries wolf is one nobody reads — which costs more than having none, because
        # a real regression then arrives among the noise.
        alternatives = case.get("expect_any", [])
        any_missing = bool(alternatives) and not any(_matches(answer, m) for m in alternatives)

        # ── the LANE, not the words (V10 W1-1) ──────────────────────────────────
        #
        # Some cases exist to assert WHERE a question went, not what came back. The 19
        # escape clauses on the pre-LLM capability short-circuit are each a measured
        # incident where a question was answered from a document before anything
        # classified it -- "how many work orders are open?" from the building-hours prose,
        # "how much energy did the building use last week?" from the room-bookings
        # document. Every one of those returned FLUENT, PLAUSIBLE text, so no marker over
        # the answer distinguishes the right lane from the wrong one. The intent does.
        _intent = str(res.get("intent") or "")
        want_intent = case.get("expect_intent")
        deny_intent = case.get("forbid_intent")
        wrong_lane = ""
        if want_intent and _intent != want_intent:
            wrong_lane = f"intent {_intent!r}, expected {want_intent!r}"
        elif deny_intent and _intent == deny_intent:
            wrong_lane = f"intent {_intent!r} is the lane this case exists to avoid"

        ok = (
            res["status"] == "OK"
            and not missing
            and not present
            and not any_missing
            and not wrong_lane
        )
        if not ok:
            failed += 1
        why = ""
        if res["status"] != "OK":
            why = f"transport {res['status']}"
        elif missing:
            why = f"missing {missing}"
        elif any_missing:
            why = f"none of {alternatives}"
        elif present:
            why = f"forbidden present {present}"
        elif wrong_lane:
            why = wrong_lane
        print(
            f"  {'PASS' if ok else 'FAIL'}  [{case.get('group','')}] "
            f"{case['question'][:62]}" + (f"\n         -> {why}" if why else "")
        )
        rows.append(
            {
                "group": case.get("group", ""),
                "question": case["question"],
                "ok": ok,
                "why": why,
                "intent": str(res.get("intent") or ""),
                "answer": answer[:1200],
            }
        )

    elapsed = time.time() - t0
    print(f"\n{len(rows) - failed}/{len(rows)} pass in {elapsed / 60:.1f} min")

    lines = [
        "# Regression probe — answers this system has already been proved to give\n",
        f"Model: `{provider}/{model}` · building `{active or 'unreported'}` · "
        f"{len(rows)} cases · **{len(rows) - failed} first-pass pass, {failed} "
        f"first-pass fail**"
        + (f" · {len(skipped)} not applicable to this building" if skipped else "")
        + "\n",
        "Each case asserts a FACT the registers hold — a figure, a record id, a department "
        "code — not a phrasing, so a reworded answer passes and a wrong figure fails.\n",
        "**Every case was asked once.** No result here was retried, so a failure is a "
        "first-pass failure and is not folded into the pass total.\n",
        "| result | group | question | why |",
        "|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {'PASS' if r['ok'] else '**FAIL**'} | {r['group']} | "
            f"{r['question'][:70]} | {r['why']} |"
        )
    # THE ANSWER, for every failure. A probe that reports "missing ['ws-']" and not what
    # came back instead cannot tell a broken system from a badly chosen marker, and the
    # first thing anyone does with it is re-ask the question by hand.
    fails = [r for r in rows if not r["ok"]]
    if fails:
        lines.append("")
        lines.append("## What came back instead")
        lines.append("")
        for r in fails:
            lines.append(f"### {r['question']}")
            lines.append("")
            lines.append(f"- **why:** {r['why']} · **intent:** `{r['intent']}`")
            lines.append("")
            lines.append("```")
            lines.append((r["answer"] or "")[:900])
            lines.append("```")
            lines.append("")
    Path(args.out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[written] {args.out}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
