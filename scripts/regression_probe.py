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

HOW LONG IT TOOK, PER LANE
--------------------------
Every case also records the time the request actually took, and the run reports p50/p95
per lane with the count beside them. CAVEAT-500 is why: the same question came back in
10.7 s, then 61.1 s, then 13.3 s, and on a fourth ask exceeded the client timeout — so a
TIMEOUT could not be told apart from a defect, and the orientation note's "typical answer
14 s" survived none of it. One typical figure cannot describe that; a median and a tail
per lane can, and a slow case is then visibly slow rather than mysteriously failed.

THE RESPONSE CACHE IS FLUSHED FIRST (BUG-662)
---------------------------------------------
The orchestrator caches answers for an hour. A question asked by hand shortly before a run
was answered from that cache: PASS in 0.0 s, lane never exercised — and a cached answer
produced BEFORE a code change passes a case the change has broken, which is the one
condition this probe exists to catch. So every run starts by deleting `resp_cache:*` in the
Redis container and printing how many keys went. If that fails, the report says so at the
top, loudly, instead of proceeding as though it had worked. `--no-flush` is for measuring the
cache deliberately. Any case answered in under a second is flagged as a possible cache hit
either way, because a flush can race a concurrent writer.

    python scripts/regression_probe.py              # all cases
    python scripts/regression_probe.py --only registers
    python scripts/regression_probe.py --baseline   # write the current answers as the record
    python scripts/regression_probe.py --no-flush   # measure cache hits on purpose
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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


#: Number words a register answer plausibly uses. Beyond twenty, answers use digits.
_NUMBER_WORDS = {
    0: "zero",
    1: "one",
    2: "two",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
    9: "nine",
    10: "ten",
    11: "eleven",
    12: "twelve",
    13: "thirteen",
    14: "fourteen",
    15: "fifteen",
    16: "sixteen",
    17: "seventeen",
    18: "eighteen",
    19: "nineteen",
    20: "twenty",
}
_WORD_NUMBERS = {w: n for n, w in _NUMBER_WORDS.items()}


def _as_small_number(token: str):
    """The integer a marker names, in digits or in words, or None if it is not one."""
    if token.isdigit() and int(token) in _NUMBER_WORDS:
        return int(token)
    return _WORD_NUMBERS.get(token)


def _matches(answer: str, marker: str) -> bool:
    """Case-insensitive, and tolerant of the separators a model renders numbers with.

    A model writes 2,728 or 2728 or 2 728 for the same figure, and an en-dash where the
    register has a hyphen. Failing a regression check on typography would train whoever
    runs this to ignore it, which is worse than not having it.
    """
    a = answer.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    a = a.replace("’", "'").replace(" ", " ").replace("\xa0", " ")
    m = marker.lower().replace(",", "").replace("‑", "-").replace("–", "-")
    n = _as_small_number(m.strip())
    if n is None:
        return m in a
    # A SMALL NUMBER IS THE SAME FACT IN WORDS OR DIGITS (CAVEAT-600). 'Which stakeholder
    # groups does DEP-13 serve?' was marked FAIL for missing the word 'three' while answering
    # '3 stakeholder groups' and naming all three correctly. A probe that fails on which
    # notation the model chose is measuring its prose, not the building's answer. Whole words
    # only, so '3' does not match inside '23'; and only when the marker is ITSELF just a
    # number, so a marker like '3 open work orders' keeps its exact wording.
    return any(
        re.search(rf"(?<![\w.]){re.escape(form)}(?![\w.])", a)
        for form in (str(n), _NUMBER_WORDS[n])
    )


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


# ── the response cache (BUG-662) ────────────────────────────────────────────────

#: The Redis container CLAUDE.md names for the cache flush. Not `ontosage-redis`.
REDIS_CONTAINER = "redis-memory-store"

#: The key pattern the orchestrator's response cache writes under.
RESP_CACHE_PATTERN = "resp_cache:*"

#: How many keys one DEL is handed. Bounded so a large cache cannot overrun a command line.
_DEL_BATCH = 200

#: A real pipeline answer has never been measured below this. A case under it is far more
#: likely to have come from the cache than from the lanes it claims to exercise.
POSSIBLE_CACHE_HIT_S = 1.0


def _redis_cli(container: str, args: List[str], run=subprocess.run) -> Tuple[bool, str]:
    """(ok, stdout-or-reason) for one redis-cli invocation inside the container.

    Arguments go to `docker exec` as a list — no shell — so a key is passed exactly as SCAN
    returned it. `run` is injectable so the logic is testable without Docker.
    """
    cmd = ["docker", "exec", container, "redis-cli", *args]
    try:
        proc = run(cmd, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        return False, "docker is not on PATH"
    except subprocess.TimeoutExpired:
        return False, f"redis-cli {args[0]} timed out after 60 s"
    except Exception as exc:  # the flush must report, never crash the probe
        return False, f"{type(exc).__name__}: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        return False, f"exit {proc.returncode}: {(err or out)[:200]}"
    # redis-cli reports a lost connection on stdout with exit 0 in some versions, and an
    # error reply as "(error) ..." or "ERR ...". Either one means the command did not happen.
    lowered = out.lower()
    if "could not connect" in lowered or lowered.startswith(("(error)", "err ")):
        return False, out[:200]
    return True, out


def flush_response_cache(container: str = REDIS_CONTAINER, run=subprocess.run) -> Dict[str, Any]:
    """Delete every `resp_cache:*` key. Returns what happened, and never raises.

    {"ok": bool, "removed": int, "remaining": int | None, "error": str}

    Two steps rather than CLAUDE.md's `--scan | xargs DEL` pipeline, for one reason: in that
    pipeline a SCAN that cannot reach Redis feeds xargs nothing, xargs exits 0, and the flush
    reports "0 removed" — a failure indistinguishable from an empty cache. Here each step's
    own exit status is checked, and the count is the sum of DEL's integer replies.
    """
    ok, out = _redis_cli(container, ["--scan", "--pattern", RESP_CACHE_PATTERN], run)
    if not ok:
        return {"ok": False, "removed": 0, "remaining": None, "error": f"scan failed: {out}"}
    keys = [line.strip() for line in out.splitlines() if line.strip()]
    removed = 0
    for start in range(0, len(keys), _DEL_BATCH):
        ok, reply = _redis_cli(container, ["DEL", *keys[start : start + _DEL_BATCH]], run)
        if not ok:
            return {
                "ok": False,
                "removed": removed,
                "remaining": None,
                "error": f"DEL failed: {reply}",
            }
        try:
            removed += int(reply.split()[-1])
        except (IndexError, ValueError):
            return {
                "ok": False,
                "removed": removed,
                "remaining": None,
                "error": f"DEL returned {reply[:80]!r}, not a count",
            }
    # Re-scan: a key written between the scan and now (a user asking through Open WebUI
    # while the probe starts) survives the flush. That is not a failure, but it is stated.
    ok, out = _redis_cli(container, ["--scan", "--pattern", RESP_CACHE_PATTERN], run)
    remaining = len([ln for ln in out.splitlines() if ln.strip()]) if ok else None
    return {"ok": True, "removed": removed, "remaining": remaining, "error": ""}


def cache_status_lines(flush: Optional[Dict[str, Any]]) -> List[str]:
    """What the report says about the cache, at the TOP. `flush` None means --no-flush."""
    if flush is None:
        return [
            "> **RESPONSE CACHE DELIBERATELY NOT FLUSHED (`--no-flush`).** Any case below may "
            "have been answered from the cache without running its lane; this run measures "
            "the cache, not the pipeline.\n",
        ]
    if not flush.get("ok"):
        return [
            "> ## WARNING — THE RESPONSE CACHE WAS NOT FLUSHED\n"
            f"> {flush.get('error') or 'unknown error'}\n>\n"
            "> Any question asked in the last hour may have been answered from the cache: a "
            "PASS below may be an answer produced BEFORE the change under test, and its lane "
            "was never exercised (BUG-662). Flush by hand and re-run before trusting this.\n",
        ]
    line = f"Response cache flushed before the run: {flush.get('removed', 0)} key(s) removed."
    if flush.get("remaining"):
        line += (
            f" **{flush['remaining']} key(s) reappeared immediately** — something else is "
            "writing to the cache while the probe runs."
        )
    return [line + "\n"]


def possible_cache_hit(row: Dict[str, Any]) -> bool:
    """A case that completed, successfully, faster than any pipeline answers."""
    return (
        str(row.get("status") or "") == "OK"
        and float(row.get("seconds") or 0.0) < POSSIBLE_CACHE_HIT_S
    )


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


#: The smallest lane a p95 is printed for. A percentile is a claim about a distribution and
#: four observations are not one — printing "p95 = 61.1 s" over three cases would repeat the
#: exact mistake CAVEAT-500 records, where one slow observation was read as a property of the
#: system. Below this the run prints the count and the median and says nothing further.
P95_MIN_SAMPLES = 5

#: Below this n the nearest-rank p95 IS the slowest observation, because ceil(0.95 * n) == n
#: for every n < 20. The figure is still real and still worth printing; it is marked so that
#: nobody reads a single slow case as a tail.
P95_IS_THE_SLOWEST_BELOW = 20


def _percentile(values: List[float], q: float) -> Optional[float]:
    """The OBSERVED value at the nearest rank — never an interpolation.

    A linearly interpolated median over an even count reports a duration no request ever
    took. For a figure whose whole purpose is to say "this is how long a question in this
    lane actually waits", an invented number is worse than a coarse one: it cannot be
    matched back to a case, and the case is the thing you go and look at.

    Nearest rank, inclusive: rank = ceil(q * n), 1-based. Returns None for no samples.
    """
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return ordered[rank - 1]


def _lane_latency(lane: str, lane_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """p50/p95/slowest for one lane, with the n that makes them readable."""
    seconds = [float(r.get("seconds") or 0.0) for r in lane_rows]
    n = len(seconds)
    slowest_row: Optional[Dict[str, Any]] = None
    if lane_rows:
        slowest_row = max(lane_rows, key=lambda r: float(r.get("seconds") or 0.0))
    return {
        "lane": lane,
        "n": n,
        "p50": _percentile(seconds, 0.50),
        # A p95 is withheld rather than approximated when the lane is too small to have one.
        "p95": _percentile(seconds, 0.95) if n >= P95_MIN_SAMPLES else None,
        "p95_is_the_slowest": n < P95_IS_THE_SLOWEST_BELOW,
        "slowest": max(seconds) if seconds else None,
        "slowest_question": str((slowest_row or {}).get("question") or ""),
        # A timed-out case contributes the wait the client sat through, which is real, and is
        # NOT the time the answer would have taken. Counting them keeps the two apart.
        "timed_out": sum(1 for r in lane_rows if str(r.get("status") or "").startswith("TIMEOUT")),
    }


def _latency_by_lane(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One latency summary per lane, plus an ALL LANES row when there is more than one.

    The lane is the case's own group — the label already printed in square brackets — so
    the workload the percentile describes is the workload the case list names, not a
    bucket invented for the report.
    """
    lanes: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        lanes.setdefault(str(r.get("group") or "(ungrouped)"), []).append(r)
    stats = [_lane_latency(lane, lanes[lane]) for lane in sorted(lanes)]
    if len(lanes) > 1:
        stats.append(_lane_latency("ALL LANES", list(rows)))
    return stats


def _secs(value: Optional[float]) -> str:
    """A duration, or an em dash where there is no figure to print."""
    return "—" if value is None else f"{value:.1f}"


def _p95_cell(stat: Dict[str, Any]) -> str:
    """The p95 as printed: blank below the minimum n, marked while it is just the slowest."""
    if stat["p95"] is None:
        return f"— (n<{P95_MIN_SAMPLES})"
    return _secs(stat["p95"]) + ("*" if stat["p95_is_the_slowest"] else "")


def _latency_lines(rows: List[Dict[str, Any]]) -> List[str]:
    """The per-lane latency section of the written report."""
    stats = _latency_by_lane(rows)
    if not stats:
        return []
    lines = [
        "",
        "## Latency per lane",
        "",
        "Every figure here is an OBSERVED request time taken at the nearest rank — no "
        "interpolation, no mean, no estimate — so each one is a wait some question in that "
        "lane actually had.",
        "",
        f"A p95 is printed only for a lane of at least {P95_MIN_SAMPLES} cases. A figure "
        f"marked `*` comes from a lane of fewer than {P95_IS_THE_SLOWEST_BELOW} cases, "
        "where the nearest-rank p95 is the slowest case itself rather than a tail.",
        "",
        "A case that timed out contributes the time the client waited before giving up. "
        "That is a real wait and it is not the time the answer would have taken, so the "
        "count is stated separately (CAVEAT-500: a timeout that cannot be told apart from "
        "a defect teaches whoever reads this to ignore both).",
        "",
        "| lane | n | p50 s | p95 s | slowest s | timed out | slowest case |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in stats:
        lines.append(
            f"| {s['lane']} | {s['n']} | {_secs(s['p50'])} | {_p95_cell(s)} | "
            f"{_secs(s['slowest'])} | {s['timed_out']} | {s['slowest_question'][:60]} |"
        )
    return lines


def _latency_console_lines(rows: List[Dict[str, Any]]) -> List[str]:
    """The same figures for the terminal, so a slow lane is visible without opening a file."""
    stats = _latency_by_lane(rows)
    if not stats:
        return []
    out = [
        "",
        "latency per lane — observed request times at the nearest rank, not interpolated",
        f"  {'lane':<22}{'n':>4}{'p50 s':>9}{'p95 s':>11}{'slowest s':>12}{'t/o':>5}",
    ]
    for s in stats:
        out.append(
            f"  {s['lane'][:22]:<22}{s['n']:>4}{_secs(s['p50']):>9}"
            f"{_p95_cell(s):>11}{_secs(s['slowest']):>12}{s['timed_out']:>5}"
        )
    out.append(
        f"  * a lane of fewer than {P95_IS_THE_SLOWEST_BELOW} cases: the nearest-rank p95 "
        "is its slowest case"
    )
    return out


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
    ap.add_argument(
        "--no-flush",
        action="store_true",
        help="do NOT flush resp_cache:* first — only for measuring the cache deliberately",
    )
    ap.add_argument(
        "--redis-container",
        default=REDIS_CONTAINER,
        help="the container the response cache lives in",
    )
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

    # ── BUG-662: a cached answer is not a first pass ────────────────────────────
    #
    # Flushed BEFORE anything is asked, and the outcome printed before the first case so a
    # failed flush is the first thing a reader of the console sees, not the last.
    flush: Optional[Dict[str, Any]] = None
    if args.no_flush:
        print("response cache: NOT flushed (--no-flush) — cases may be served from the cache")
    else:
        flush = flush_response_cache(args.redis_container)
        if flush["ok"]:
            print(
                f"response cache: flushed {flush['removed']} resp_cache key(s) from "
                f"{args.redis_container}"
                + (f" ({flush['remaining']} reappeared)" if flush.get("remaining") else "")
            )
        else:
            bar = "!" * 78
            print(
                f"{bar}\n!! RESPONSE CACHE NOT FLUSHED: {flush['error']}\n"
                "!! A PASS below may be a cached answer from BEFORE the change under test.\n"
                f"{bar}"
            )

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
        # THE TIME THIS CASE ACTUALLY TOOK, measured around the request by `_ask` and carried
        # through untouched. Never derived from the run total divided by the case count: that
        # is exactly the single typical figure CAVEAT-500 shows says nothing, and it would
        # hand every case the same number while one of them sat for a minute.
        seconds = float(res.get("elapsed_s") or 0.0)
        row = {
            "group": case.get("group", ""),
            "question": case["question"],
            "ok": ok,
            "why": why,
            "intent": str(res.get("intent") or ""),
            "seconds": seconds,
            "status": str(res.get("status") or ""),
            "answer": answer[:1200],
        }
        row["possible_cache_hit"] = possible_cache_hit(row)
        print(
            f"  {'PASS' if ok else 'FAIL'} {seconds:>7.1f}s  [{case.get('group','')}] "
            f"{case['question'][:62]}"
            + (f"\n         -> {why}" if why else "")
            + ("\n         -> possible cache hit" if row["possible_cache_hit"] else "")
        )
        rows.append(row)

    elapsed = time.time() - t0
    print(f"\n{len(rows) - failed}/{len(rows)} pass in {elapsed / 60:.1f} min")
    for line in _latency_console_lines(rows):
        print(line)
    cache_hits = [r for r in rows if r.get("possible_cache_hit")]
    if cache_hits:
        print(
            f"{len(cache_hits)} case(s) answered in under {POSSIBLE_CACHE_HIT_S:.1f} s — "
            "possible cache hit(s); their lanes may not have run"
        )
    if flush is not None and not flush["ok"]:
        print(f"!! reminder: the response cache was NOT flushed ({flush['error']})")

    lines = [
        "# Regression probe — answers this system has already been proved to give\n",
        # BUG-662: what the cache did, FIRST. A failed flush makes every PASS below suspect.
        *cache_status_lines(flush),
        f"Model: `{provider}/{model}` · building `{active or 'unreported'}` · "
        f"{len(rows)} cases · **{len(rows) - failed} first-pass pass, {failed} "
        f"first-pass fail**"
        + (f" · {len(skipped)} not applicable to this building" if skipped else "")
        + "\n",
        "Each case asserts a FACT the registers hold — a figure, a record id, a department "
        "code — not a phrasing, so a reworded answer passes and a wrong figure fails.\n",
        "**Every case was asked once.** No result here was retried, so a failure is a "
        "first-pass failure and is not folded into the pass total.\n",
        "**How long each one took is recorded**, and summarised per lane below. A single "
        "typical figure hid a 10x spread across identical re-asks (CAVEAT-500), so a slow "
        "case reads as slow here rather than as a mystery failure.\n",
        "| result | group | question | secs | why |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        why_cell = r["why"]
        if r.get("possible_cache_hit"):
            why_cell = (why_cell + " · " if why_cell else "") + "**possible cache hit**"
        lines.append(
            f"| {'PASS' if r['ok'] else '**FAIL**'} | {r['group']} | "
            f"{r['question'][:70]} | {_secs(r.get('seconds'))} | {why_cell} |"
        )
    if cache_hits:
        lines += [
            "",
            f"**{len(cache_hits)} case(s) completed in under {POSSIBLE_CACHE_HIT_S:.1f} s and "
            "are marked possible cache hits.** No pipeline answer has been measured that fast; "
            "a PASS marked this way says nothing about the lane it names (BUG-662).",
        ]
    lines.extend(_latency_lines(rows))
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
