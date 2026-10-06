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
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests

REPO = Path(__file__).resolve().parent.parent

#: Openings the system uses when it cannot ground an answer. An answer that BEGINS with one of these
#: is a decline, whatever follows. Kept as the system's own wording so a new decline phrasing shows
#: up here as a diff rather than silently counting as an answer.
_DECLINE_MARKERS = (
    "i couldn't answer that from",
    # BUG-1252. `clarification.lead_read_but_off_topic` opens with this when the relevance gate
    # deleted an answer on a turn that had COUNTED rows out of a store -- the same decline, with
    # a first sentence that stops asserting the building could not answer. Without these two the
    # gate would score it as an ANSWER, and a decline counted as an answer is the direction that
    # HIDES a regression (lessons #141). Verified over 2,985 stored answers (the 73-probe pack
    # plus every docs/phase0/*.jsonl): zero reclassified by this addition, and zero of them
    # already contain the lead, so that zero is real and not a vacuous match.
    "i couldn't put an answer together",
    "i could not put an answer together",
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
    # Found running the gate 2026-10-03 (unrelated to that day's product changes -- the
    # decline text alone, with no evidence panel appended, was already misclassified): the
    # live wording for this exact question had drifted to "There is no recorded
    # air-pressure sensor for Room 2.01." sometime after the marker above was written, and
    # nothing had re-asked gate case #70 with this wording until now.
    "there is no recorded air-pressure sensor",
    "there is no solar irradiance measurement",
    "no readings were found for",
    # A6 (QA-trial plan, 2026-10-02). `session_recall`'s own decline when a provenance or
    # recall question is asked with no prior turn in the conversation -- gate case #37,
    # "What is the evidence behind your answer about the coolest room?", classified
    # `answered` (`got_kind=answered, status=ok`) against a `None` first turn. The classifier
    # cannot fail either direction on the one case that is Wave D's own subject matter until
    # this is here. Verified: zero of the 73 stored pack answers already contain it, so this
    # is zero reclassified, not a vacuous match.
    "nothing has been asked in this conversation yet",
)

#: Declines whose wording carries the REFERENT in the middle, so no fixed substring spans them.
#:
#: "I couldn't answer that about **Room2.01** from Abacws Building's records" is the same decline
#: as "I couldn't answer that from ...", with the room named. The literal marker above does not
#: span the inserted name, so the gate scored that decline as an ANSWER -- and a decline counted
#: as an answer is the direction that hides a regression rather than inventing one. Found
#: 2026-09-23 while measuring an intermittent question; the shipped pack happens to contain none
#: of this variant, so its recorded counts are unaffected.
_DECLINE_PATTERNS = (
    re.compile(r"i could ?n[o']?t answer that\s+about\b.{0,80}?\bfrom\b"),
    re.compile(r"i could ?n[o']?t find\s+.{0,60}?\bin (?:the )?(?:building|records)\b"),
    # "there is no air-pressure sensor INSTALLED IN Room 2.01" -- the same honest decline the
    # literal marker below spells "...sensor DATA available for room 2.01". The quantity and the
    # tail both vary, so the fixed string matched one phrasing and scored the other as an ANSWER.
    # The system was right both times; the gate was wrong the second time (pack index 70).
    #
    # DELIBERATELY NARROW, and the first two attempts show why. `there (?:is|are) no .{0,40}
    # sensors?` also matched "there are no GAPS IN SENSOR COVERAGE" -- a completeness answer
    # asserting the opposite -- and a rule keyed on `installed` alone matched the label
    # "CO2 Level Sensor installed-node 3.07". Requiring "installed/fitted IN|AT|FOR" keeps the
    # claim and rejects both. Checked against every stored pack answer: zero reclassified.
    re.compile(
        r"there (?:is|are) no\b[^.]{0,40}?\bsensors?\s+(?:installed|fitted)\s+(?:in|at|for)\b"
    ),
    # THIRD wording of the same decline, same day: "I don't have any air-pressure data for
    # Room 2.01", followed by a list of the room's OTHER sensors. The asked quantity is still
    # declined, and offering what the building does have does not make it an answer to the
    # question. Matches none of the 73 stored answers, so the baseline is untouched.
    #
    # Three phrasings in one day is the real finding here, and it is recorded as CAVEAT-887:
    # a marker list cannot keep up with a system free to reword its declines, and the durable
    # test is whether the answer gives a figure FOR THE QUANTITY ASKED.
    re.compile(r"i do ?n[o']?t have any\b[^.]{0,40}?\bdata\b"),
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
_PUNCT = str.maketrans(
    {
        "‑": "-",
        "‐": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "−": "-",
        "’": "'",
        "‘": "'",
        "“": '"',
        "”": '"',
        " ": " ",
    }
)


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
    if any(p.search(head) for p in _DECLINE_PATTERNS):
        return "declined"
    return "answered"


#: Calendar spans the gate can resolve, tried in order. "day before yesterday" must be matched
#: first or its "yesterday" half would win. Offsets are days back from today; "this week" runs
#: Monday to today, "last week" is the previous Monday to Sunday.
_RELATIVE_DAY_RULES = (
    (re.compile(r"\bday before yesterday\b"), "day_before_yesterday"),
    (re.compile(r"\byesterday\b"), "yesterday"),
    (re.compile(r"\b(today|this morning|this afternoon|this evening)\b"), "today"),
    (re.compile(r"\blast week\b"), "last_week"),
    (re.compile(r"\bthis week\b"), "this_week"),
)

#: Which store a question's data lives in, so the gate asks the RIGHT table whether the day has
#: readings. A question with no entry here keeps its stored label: asking energy whether
#: occupancy happened is how a correct answer gets scored as a regression.
_TOPIC_TABLES = (
    (re.compile(r"\b(electric\w*|energy|kwh)\b"), "energy_data"),
    (re.compile(r"\b(occupan\w*|occupied|people)\b"), "occupancy_data"),
)


def _monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _relative_span(question: str, today: date) -> Optional[Tuple[date, date]]:
    """The calendar span a question's relative day words name, or None when it names none.

    Several words in one question widen the span to cover all of them, so "this week's use
    against last week's" is the whole of both weeks.
    """
    low = (question or "").lower()
    spans: List[Tuple[date, date]] = []
    # "day before yesterday" contains "yesterday": once it has named its day, the bare word must
    # not add a second span, or the answer widens to two days.
    day_before = bool(_RELATIVE_DAY_RULES[0][0].search(low))
    for pattern, word in _RELATIVE_DAY_RULES:
        if not pattern.search(low):
            continue
        if word == "day_before_yesterday":
            spans.append((today - timedelta(days=2), today - timedelta(days=2)))
        elif word == "yesterday":
            if day_before:
                continue
            spans.append((today - timedelta(days=1), today - timedelta(days=1)))
        elif word == "today":
            spans.append((today, today))
        elif word == "last_week":
            start = _monday_of(today) - timedelta(days=7)
            spans.append((start, start + timedelta(days=6)))
        elif word == "this_week":
            spans.append((_monday_of(today), today))
    if not spans:
        return None
    return min(s for s, _ in spans), max(e for _, e in spans)


def _table_for_question(question: str) -> Optional[str]:
    """The store whose rows answer this question, or None when the gate cannot tell."""
    low = (question or "").lower()
    for pattern, table in _TOPIC_TABLES:
        if pattern.search(low):
            return table
    return None


def expected_for_relative_day(
    case: Dict[str, Any],
    today: date,
    has_data_for: Callable[[date, str], bool],
) -> Dict[str, Any]:
    """The kind a relative-day case should give TODAY, and the calendar day it is about.

    A stored label was recorded on the day the pack was captured. "Yesterday" names a different
    day every day, so for a question whose words resolve to a calendar date the expectation is
    derived from the data on that date: readings there -> answered, none -> declined. Refusals
    are not data-dependent and keep their label, as does any question with no topic table to
    check. A failed data check falls back to the label rather than guessing.

    `has_data_for(day, table)` is injected so tests fix the clock and the data.
    """
    stored = case.get("expected_kind", "")
    span = _relative_span(case.get("question", ""), today)
    if span is None:
        return {"resolved_date": None, "expected_kind": stored, "basis": "stored label"}
    first, last = span
    resolved = first.isoformat() if first == last else f"{first.isoformat()}..{last.isoformat()}"
    keep = {"resolved_date": resolved, "expected_kind": stored}
    if stored == "refused":
        return {**keep, "basis": "stored label: a refusal does not depend on the data"}
    table = _table_for_question(case.get("question", ""))
    if table is None:
        return {**keep, "basis": "stored label: no data table for this topic"}
    days = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    try:
        has = any(has_data_for(d, table) for d in days)
    except Exception as exc:
        return {**keep, "basis": f"stored label: data check failed ({type(exc).__name__})"}
    return {
        "resolved_date": resolved,
        "expected_kind": "answered" if has else "declined",
        "basis": f"{table} {'has' if has else 'has no'} readings for {resolved}",
    }


def mysql_has_data_factory(tz_name: Optional[str]) -> Callable[[date, str], bool]:
    """A `has_data_for(day, table)` that asks MySQL, opening the connection on first use.

    The day is a BUILDING-LOCAL calendar date, converted to the stores' UTC span the same way
    the product converts it (`requested_interval.to_store`). Connection settings come from the
    environment, then the `.env` the gate already reads its token from.
    """
    from orchestrator.services.requested_interval import to_store
    from shared.db_clock import UTC_SESSION_INIT

    tables = {t for _, t in _TOPIC_TABLES}
    state: Dict[str, Any] = {"conn": None}

    def _conn():
        if state["conn"] is None:
            import os

            import pymysql

            env = _dotenv()

            def pick(key: str, default: str) -> str:
                return os.environ.get(key) or env.get(key) or default

            state["conn"] = pymysql.connect(
                host=pick("MYSQL_HOST", "localhost"),
                port=int(pick("MYSQL_PORT", "3306")),
                user=pick("MYSQL_USER", "root"),
                password=pick("MYSQL_PASSWORD", ""),
                database=pick("MYSQL_DATABASE", "sensordb"),
                init_command=UTC_SESSION_INIT,
            )
        return state["conn"]

    def has_data_for(day: date, table: str) -> bool:
        if table not in tables:
            raise ValueError(f"not a gate data table: {table!r}")
        start = to_store(datetime(day.year, day.month, day.day), tz_name)
        end = to_store(datetime(day.year, day.month, day.day) + timedelta(days=1), tz_name)
        with _conn().cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {table} WHERE datetime >= %s AND datetime < %s LIMIT 1",
                (start, end),
            )
            return cur.fetchone() is not None

    return has_data_for


def _dotenv() -> Dict[str, str]:
    """KEY=VALUE pairs from the first `.env*` file that carries any, without comments."""
    out: Dict[str, str] = {}
    for name in (".env", ".env1", ".env2", ".env3"):
        path = REPO / name
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                out.setdefault(k.strip(), v.split(" #")[0].strip().strip('"').strip("'"))
    return out


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
    rows = [
        json.loads(x)
        for x in (pack / "answers.jsonl").read_text(encoding="utf-8").splitlines()
        if x.strip()
    ]
    verdicts = json.loads((pack / "review.json").read_text(encoding="utf-8")).get("verdicts", {})
    for r in rows:
        v = verdicts.get(str(r["n"]), ["UNREVIEWED", ""])
        r["verdict"], r["note"] = v[0], v[1]
        r["expected_kind"] = classify(r.get("answer", ""))
    return rows


def ask(
    base: str,
    question: str,
    model: str,
    token: str,
    timeout: int,
    email: str = "",
    chat_id: str = "",
) -> Dict[str, Any]:
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
            json={
                "model": model,
                "messages": [{"role": "user", "content": question}],
                "stream": False,
            },
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
    ap.add_argument(
        "--email",
        default="facility01@example.com",
        help="forwarded user; the ROLE comes from this and governs what is allowed",
    )
    ap.add_argument("--timeout", type=int, default=420)
    ap.add_argument("--only", default="", help="comma list of pack indexes")
    ap.add_argument(
        "--include-weak",
        action="store_true",
        help="also re-ask the questions that do NOT currently answer, to see if a wave fixed one",
    )
    ap.add_argument("--out", default=str(REPO / "scripts" / "outputs"))
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    token = args.token or pipeline_key()
    if not token:
        print(
            "no PIPELINE_API_KEY in the environment or any .env — every request would be 401",
            file=sys.stderr,
        )
        return 2

    rows = load_pack(Path(args.pack))
    wanted = {int(x) for x in args.only.split(",") if x.strip().isdigit()}
    subjects = [
        r
        for r in rows
        if (not wanted or r["n"] in wanted) and (args.include_weak or r["verdict"] == "GOOD")
    ]
    if not subjects:
        print("nothing to check")
        return 0

    stamp_run = datetime.now().strftime("%H%M%S")
    print(
        f"re-asking {len(subjects)} question(s) from {Path(args.pack).name} "
        f"as {args.email or '(no identity - runs as readonly)'}\n"
    )
    # "Yesterday" is resolved against the SYSTEM clock and the building's zone, once per run, so
    # every case in one run is judged against the same day.
    today = datetime.now().date()
    try:
        from orchestrator.services.requested_interval import building_tz

        tz_name = building_tz()
    except Exception:
        tz_name = None
    has_data_for = mysql_has_data_factory(tz_name)
    results, regressions, improvements, intermittents = [], [], [], []
    for i, r in enumerate(subjects, 1):
        # A relative-day case is judged against the data on the day it names, not the stored
        # label recorded on the capture day (the stored kind is kept beside it for the reader).
        rel = expected_for_relative_day(r, today, has_data_for)
        r["stored_kind"] = r["expected_kind"]
        r["expected_kind"] = rel["expected_kind"]
        got = ask(
            args.base,
            r["question"],
            args.model,
            token,
            args.timeout,
            email=args.email,
            chat_id=f"regr-{stamp_run}-{r['n']}",
        )
        kind = classify(got["answer"]) if not got["error"] else "empty"
        # A GOOD question must keep giving the SAME KIND of reply. An answer that became a decline
        # is the regression this exists for; a decline that became an answer is an improvement.
        ok = kind == r["expected_kind"]
        status = (
            "ok  "
            if ok
            else ("BETTER" if r["verdict"] != "GOOD" and kind == "answered" else "REGRESSED")
        )
        # CONFIRM A REGRESSION BEFORE REPORTING ONE (2026-09-23).
        #
        # Index 1 -- a two-week humidity forecast -- reported REGRESSED on a build whose changes
        # provably cannot reach it: the routing pattern does not match the question and the other
        # three changes are deliberation-lane only. Re-asked three times on that same build it
        # declined once and answered twice. One run is not a measurement of an intermittent lane,
        # and a gate that cries regression at a flake gets switched off, which costs far more than
        # the flake.
        #
        # AN INTERMITTENT IS NOT AN OK. It is reported and counted in its own category and never
        # folded into "still behave as recorded" -- a retry that succeeds is still a first-pass
        # failure (lessons.md, "report first-pass failures"). The exit code stays 0 because the
        # behaviour is not gone, and the line stays visible because it is not well either.
        if status == "REGRESSED":
            retry = ask(
                args.base,
                r["question"],
                args.model,
                token,
                args.timeout,
                email=args.email,
                chat_id=f"regr-{stamp_run}-{r['n']}-retry",
            )
            retry_kind = classify(retry["answer"]) if not retry["error"] else "empty"
            if retry_kind == r["expected_kind"]:
                status = "FLAKY"
                intermittents.append(r["n"])
                got, kind = retry, retry_kind
        if status == "REGRESSED":
            regressions.append(r["n"])
        elif status == "BETTER":
            improvements.append(r["n"])
        print(
            f"[{i:2d}/{len(subjects)}] #{r['n']:<3d} {status:9s} {r['expected_kind']:>8s} -> "
            f"{kind:<8s} {got['seconds']:6.1f}s  {r['question'][:52]}"
        )
        # `status` IS SAVED, AND IT USED NOT TO BE (CAVEAT-1398).
        #
        # `verdict` is the PACK's stored hand-read label -- almost always "GOOD", because the
        # pack is the set of questions that were judged to answer. `status` is what THIS run
        # computed. Only `verdict` was written to the file, so the artefact of the 49/51 run on
        # 2026-10-01 showed `"verdict": "GOOD"` on all fifty-one rows: a failing run whose own
        # record reads as a pass, and whose failures were recoverable only by re-deriving
        # `expected_kind != got_kind` and knowing to.
        results.append(
            {
                **{k: r[k] for k in ("n", "question", "verdict", "expected_kind")},
                "stored_kind": r["stored_kind"],
                "resolved_date": rel["resolved_date"],
                "expected_basis": rel["basis"],
                "status": status.strip(),
                "got_kind": kind,
                "seconds": round(got["seconds"], 1),
                "error": got["error"],
                "answer": got["answer"],
                "first_pass_failed": status == "FLAKY",
            }
        )

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"regression_answerability_{stamp}.json"
    # The run's own conclusion, in the file, so the artefact cannot read as a pass when it is
    # not one (CAVEAT-1398). A reader should not have to re-derive the verdict to learn it.
    path.write_text(
        json.dumps(
            {
                "pack": args.pack,
                "summary": {
                    "cases": len(subjects),
                    "steady": len(subjects) - len(regressions) - len(intermittents),
                    "regressed": regressions,
                    "intermittent": intermittents,
                    "improved": improvements,
                    "passed": not regressions,
                },
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    steady = len(subjects) - len(regressions) - len(intermittents)
    print(f"\n{steady} of {len(subjects)} still behave as recorded")
    if intermittents:
        print(f"INTERMITTENT (failed first pass, answered on re-ask): {intermittents}")
        print("   Not counted as still behaving. The lane is not gone; it is not reliable either.")
    if improvements:
        print(f"IMPROVED (a question that did not answer now does): {improvements}")
    if regressions:
        print(f"REGRESSED: {regressions}")
        print(
            "A question that used to answer no longer does. Read the saved answers before merging:"
        )
        print(f"   {path}")
        return 1
    print(f"saved {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
