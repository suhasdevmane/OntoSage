#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Grade recorded stakeholder answers into six buckets, and say why for every row.

WHAT THIS IS FOR
----------------
Before a supervisor demo the question is not "how many answers came back" -- every row of a
run comes back with status OK -- but "how often does a stakeholder question get a WEIRD
answer". This reads the output of ``scripts/ask_questions.py --out`` (the ``.md`` report or
its ``.md.jsonl`` sibling), joins each question to its bank row (stakeholder, category and
the catalogue's written ANSWER BOUNDARY), and puts every answer in exactly one bucket:

    ANSWERED              a substantive answer to what was asked
    HONEST_DECLINE        a correct refusal or honest absence -- NOT a failure
    ADD_DATA_INSTRUCTION  tells the reader to add/upload/install/ingest data, TTL or sensors
    WRONG_LANE            answered about something other than what was asked
    INCOMPLETE            a generic non-answer: template apology, timeout, budget refusal, empty
    INVENTED              a claim with no visible grounding (always LOW confidence -- a flag)

Every verdict carries a confidence (high / low), the rule that decided it, and a reason
quoting the phrase that decided it. Low-confidence rows are listed for a human to read.

    python scripts/grade_stakeholder_answers.py docs/phase0/phase0_baseline.md \\
        --bank docs/phase0/phase0_bank.jsonl --out docs/phase0/phase0_graded

writes ``<out>.md`` and ``<out>.jsonl``.

WHY NOT ``corpus_replay._heuristic_grade``
------------------------------------------
That grader has no notion of a wrong lane, an add-data instruction or an invented claim, and
its "answered" verdict still leans on the shape of a response. The six buckets here are the
ones the readiness plan (tasks/READINESS_PLAN_2026-09-17.md) asks the demo to be judged by.
It deliberately does NOT import the system's own guards (grounding_guard, absence_guard):
a grader built from the system's heuristics cannot see the system's blind spots.

KNOWN GRADER FAILURES THIS AVOIDS (lessons #20-22, BUG-189, BUG-191)
--------------------------------------------------------------------
* **Digit presence is never evidence of an answer.** "Any number means it answered" scored a
  fabrication as PASS and three refusals as PASS (the "2" inside "bldg2"). No rule here
  credits ANSWERED because a digit appears. Floors and rooms are read only from explicit
  labels ("floor 2", "second-floor", "Room 2.01"), never from a bare number, so "0.65 hr"
  or "£0.3102" is not a room.
* **An honest decline is not a failure.** For a question the building cannot answer, or one
  the catalogue's boundary says must be refused, the decline IS the correct answer. A grader
  that scores it as failure teaches the system to overstep.
* **The grade is about SHAPE, not truth.** Whether "3 open work orders" is the right count is
  not knowable from text. INVENTED is therefore only ever a low-confidence flag, raised by a
  handful of specific, observed patterns; it is not a fact-check.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parent.parent

ANSWERED = "ANSWERED"
HONEST_DECLINE = "HONEST_DECLINE"
ADD_DATA = "ADD_DATA_INSTRUCTION"
WRONG_LANE = "WRONG_LANE"
INCOMPLETE = "INCOMPLETE"
INVENTED = "INVENTED"
BUCKETS = (ANSWERED, HONEST_DECLINE, ADD_DATA, WRONG_LANE, INCOMPLETE, INVENTED)
# What the owner calls a weird answer. HONEST_DECLINE is deliberately not in it.
WEIRD = (ADD_DATA, WRONG_LANE, INCOMPLETE, INVENTED)
HIGH, LOW = "high", "low"


# ─────────────────────────────────────────────────────────────────────────────────────────
# Loading
# ─────────────────────────────────────────────────────────────────────────────────────────

_MD_HEADER = re.compile(
    r"^### (?P<q>.+) — run (?P<run>\d+) \((?P<secs>[\d.]+) s, (?P<status>[^)]*)\)\s*$",
    re.M,
)


def parse_markdown_report(text: str) -> List[Dict]:
    """Rows from an ``ask_questions.py --out`` markdown report (answers cut at 4,000 chars)."""
    rows: List[Dict] = []
    heads = list(_MD_HEADER.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        chunk = text[m.end() : end].strip("\n")
        # The writer emits: blank, ```, answer, ```, blank. Strip exactly one fence pair so
        # an answer that itself contains a fence survives.
        if chunk.startswith("```"):
            chunk = chunk[3:].lstrip("\n")
        chunk = chunk.rstrip()
        if chunk.endswith("```"):
            chunk = chunk[:-3].rstrip("\n")
        rows.append(
            {
                "q": m.group("q"),
                "run": int(m.group("run")),
                "secs": float(m.group("secs")),
                "status": m.group("status").strip(),
                "answer": chunk,
            }
        )
    return rows


def _read_jsonl(path: Path) -> List[Dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def load_answers(path: Path) -> Tuple[List[Dict], str]:
    """Rows plus a one-line note saying which file the answers were actually read from.

    The ``.md`` report truncates each answer at 4,000 characters, which cuts the source
    chips and footers off long answers; its ``.md.jsonl`` sibling is complete but is
    APPENDED to, so a re-run with the same ``--out`` leaves earlier rows in front. The
    sibling is used when its last N questions match the report's N in order.
    """
    if path.suffix == ".jsonl":
        return _read_jsonl(path), f"read {path.name}"
    sibling = path.with_name(path.name + ".jsonl")
    md_rows = parse_markdown_report(path.read_text(encoding="utf-8")) if path.is_file() else []
    if sibling.is_file():
        js_rows = _read_jsonl(sibling)
        if not md_rows:
            return js_rows, (
                f"{path.name} not found or empty; read {sibling.name} "
                f"({len(js_rows)} rows — a run still in progress is graded as partial)"
            )
        tail = js_rows[-len(md_rows) :]
        if len(tail) == len(md_rows) and all(a["q"] == b["q"] for a, b in zip(tail, md_rows)):
            skipped = len(js_rows) - len(tail)
            note = f"read {sibling.name} (complete answers)"
            if skipped:
                note += f"; ignored {skipped} earlier appended row(s) not in {path.name}"
            return tail, note
        return md_rows, (
            f"read {path.name}; {sibling.name} did not match it row for row, so answers are "
            "the report's 4,000-char excerpts"
        )
    if not md_rows:
        raise SystemExit(f"no answers found in {path}")
    return md_rows, f"read {path.name} (answers are 4,000-char excerpts)"


def _norm_q(q: str) -> str:
    return " ".join(normalise(q or "").lower().split())


def load_bank(path: Optional[Path]) -> Dict[str, Dict]:
    if not path:
        return {}
    return {_norm_q(r.get("question", "")): r for r in _read_jsonl(path)}


# ─────────────────────────────────────────────────────────────────────────────────────────
# Text utilities
# ─────────────────────────────────────────────────────────────────────────────────────────

_DASHES = re.compile("[‐‑‒–—―−]")


def normalise(text: str) -> str:
    """Typography only: the model writes non-breaking hyphens and curly quotes."""
    text = (text or "").replace("\r\n", "\n")
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    # Keep the em dash the templates use as a separator; fold the rest to "-".
    return _DASHES.sub(lambda m: m.group(0) if m.group(0) == "—" else "-", text)


_STOP = set(
    """
a about above across after again against all also am an and any are as at be because been
before being below between both but by can could did do does doing down during each either
else ever every few for from further had has have having here how i if in into is it its
itself just may me might more most much must my no nor not now of off on once only or other
our out over own per same shall she should so some still such than that the their them then
there these they this those through to too under until up upon very via was we were what
when where which while who whom whose why will with within without would yet you your yours
able any anything something somewhere someone thing things way ways use used using get got
make made take give given tell show find need needs needed want like likely enough
today now current currently latest next new first last right exactly each every
building buildings record records data information register registers entry entries list
lists detail details kind kinds type types specific available please let know help
question answer answers
following include including
""".split()
)


def _stem(tok: str) -> str:
    for suf in ("ities", "ation", "ings", "ing", "ies", "ied", "ed", "es", "s", "ly"):
        if tok.endswith(suf) and len(tok) - len(suf) >= 3:
            return tok[: -len(suf)]
    return tok


def content_stems(text: str) -> Set[str]:
    """Content-word stems; digits and short tokens are dropped, never counted as meaning."""
    toks = re.findall(r"[a-z][a-z0-9]*", normalise(text).lower().replace("-", " "))
    return {_stem(t) for t in toks if len(t) >= 3 and t not in _STOP}


def overlap(a: Iterable[str], b: Iterable[str]) -> Set[str]:
    """Stems shared by two sets, allowing a 4+ char prefix match (evidenc ~ evidenced)."""
    a, b = set(a), set(b)
    hits = a & b
    for x in a - hits:
        for y in b:
            short, long_ = (x, y) if len(x) <= len(y) else (y, x)
            if len(short) >= 4 and long_.startswith(short):
                hits.add(x)
                break
    return hits


def _quote(text: str, m: re.Match, pad: int = 40) -> str:
    s = max(0, m.start() - pad)
    e = min(len(text), m.end() + pad)
    frag = " ".join(text[s:e].split())
    return f'"{"..." if s else ""}{frag}{"..." if e < len(text) else ""}"'


# ─────────────────────────────────────────────────────────────────────────────────────────
# Splitting an answer into body, source chips and appended footers
# ─────────────────────────────────────────────────────────────────────────────────────────

# Paragraphs the pipeline APPENDS to an answer. They are provenance or remediation, not the
# answer, and several of them contain decline-like words ("I can't say what this figure
# covers") that would otherwise make an answered row read as a decline.
_FOOTER_PREFIXES = (
    "**Boundary",
    "**Evidence time",
    "**As measured at",
    "*Answered live from",
    "*Counted now from",
)


@dataclass
class Parsed:
    raw: str
    body: str
    sources: List[str]
    footers: List[str]
    had_followups: bool


def split_answer(answer: str) -> Parsed:
    raw = normalise(answer)
    text = re.sub(r"<details>.*?</details>", "", raw, flags=re.S)
    sources: List[str] = []
    m = re.search(r"^\*Sources:\s*(.+?)\*\s*$", text, flags=re.M)
    if m:
        sources = [s.strip() for s in re.findall(r"`([^`]+)`", m.group(1))]
        text = text[: m.start()] + text[m.end() :]
    had_followups = bool(re.search(r"\*\*You might also ask:\*\*", text))
    text = re.sub(r"^\*\*You might also ask:\*\*.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*---\s*$", "", text, flags=re.M)
    body_paras, footers = [], []
    for para in re.split(r"\n\s*\n", text):
        p = para.strip()
        if not p:
            continue
        (footers if p.startswith(_FOOTER_PREFIXES) else body_paras).append(p)
    return Parsed(raw, "\n\n".join(body_paras).strip(), sources, footers, had_followups)


_HEADING_ONLY = re.compile(r"^(?:#{1,6}\s.*|\*\*[^*\n]{1,60}\*\*:?|[^\n]{0,40}:)$")


def plain(text: str) -> str:
    """Markdown emphasis removed, so "do **not** contain" matches "do not contain".

    Found on run 3 row 14 and run 2 rows 22/23/47: the model bolds the negation, and every
    decline marker missed it, grading an honest decline as ANSWERED.
    """
    return re.sub(r"\*\*|__|(?<![\w*])\*(?=\S)|(?<=\S)\*(?![\w*])", "", text)


def lead_text(body: str, limit: int = 420) -> str:
    """The first two sentences, skipping heading-only paragraphs like '**Answer**'.

    Two sentences, not two paragraphs: run 2 row 4 opened with a substantive answer whose
    SECOND paragraph quoted a '"no evidence" status' from the data, and a paragraph-wide lead
    read that as a decline.
    """
    paras = [x for x in body.split("\n\n") if not _HEADING_ONLY.match(x.strip())]
    text = plain(" ".join(" ".join(paras).split()))
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z*\"'(])", text)
    return " ".join(sentences[:2])[:limit]


# ─────────────────────────────────────────────────────────────────────────────────────────
# Signals
# ─────────────────────────────────────────────────────────────────────────────────────────

_I = re.IGNORECASE

# Strong: the answer tells the reader to change the building's data. Observed rows:
#   run1-3 #40 "You can add it — no code changes needed: 1. Describe it in the ontology —
#     upload a TTL"; #65 "add or update it — a document carrying record-document
#     front-matter"; run1 #47 "consider installing dedicated filter-size sensors"; run1 #60
#     "install or retrieve temperature/humidity sensors"; run3 #63 "consider adding the
#     relevant sensor classes to the building model"; observability.py "Unlock:".
STRONG_ADD = [
    ("you_can_add_it", re.compile(r"\byou can add (?:it|this|them)\b", _I)),
    ("no_code_change", re.compile(r"\bno code changes? (?:is |are )?needed\b", _I)),
    ("unlock", re.compile(r"\bUnlock:")),
    (
        "upload",
        re.compile(
            r"\bupload(?:ing)? (?:a |an |the |your )?(?:TTL|\.ttl|ontology|manual|document"
            r"|policy|procedure)\b",
            _I,
        ),
    ),
    ("add_or_update", re.compile(r"\badd or update it\b", _I)),
    ("front_matter", re.compile(r"\bfront-matter\b", _I)),
    # install_sensor is checked separately (install_instruction): "Install daylight sensors
    # so lights dim" is energy ADVICE (run 2/3 row 66), not an instruction to add data.
    (
        "add_to_model",
        re.compile(
            r"\badd(?:ing)?\b[^.\n]{0,60}?\b(?:to|into) (?:the |your )?(?:building(?:'s)? )?"
            r"(?:model|ontology|sensor suite|knowledge graph)\b",
            _I,
        ),
    ),
    (
        "need_to_add",
        re.compile(
            r"\byou (?:will |would )?need to (?:add|install|upload|register|ingest|wire)\b", _I
        ),
    ),
    ("ref_properties", re.compile(r"`ref:(?:hasTimeseriesId|storedAt|hasExternalReference)`")),
    ("register_database", re.compile(r"\bregister the database\b", _I)),
    # run3 #60: "consider extending the ontology with the relevant properties and linking the
    # sensor UUIDs" -- graded a soft ask until read.
    (
        "extend_ontology",
        re.compile(
            r"\bextend(?:ing)? the (?:building(?:'s)? )?(?:ontology|model|knowledge graph)\b", _I
        ),
    ),
]

# Weak: an appended remediation footer ("Declaring the meter's boundary ... would let every
# energy answer state it") -- seen on waste, tariff and door answers in all three runs.
FOOTER_REMEDIATION = re.compile(
    r"Declaring the meter's boundary|would let every energy answer state it"
    r"|has no `ontosage:\w+` in the ontology",
    _I,
)

# "install" / "installing" only -- "installed" describes what exists.
INSTALL_SENSOR = re.compile(r"\binstall(?:ing)?\b[^.]{0,60}?\bsensors?\b", _I)
# The install is an add-DATA instruction when it is offered as the way to get an answer.
INSTALL_FOR_DATA = re.compile(
    r"\b(?:data|information|track\w*|record\w*|measur\w*|answer\w*|quer\w*|timeseries"
    r"|time-series|calculat\w*|comput\w*|analys\w*|analyz\w*|monitor\w*)\b",
    _I,
)

# Weak: the model asks the reader to hand it data (run2 #56 "please share those"; run2 #41
# "If you can provide the missing data"; run3 #7 "If you have additional data sources ...
# please share them"). Restricted to DATA nouns: run1 #25 "If you can provide the specific
# URIs or property names" asks for a pointer, not for data.
SOFT_ASK = re.compile(
    r"\bplease (?:share|send|upload)\b"
    r"|\bif you (?:can|could) (?:provide|share|supply)\b[^.]{0,40}?\b(?:data|logs?|records?"
    r"|numbers|values|figures|readings)\b"
    r"|\bif you have\b[^.]{0,80}?\b(?:data|logs?|records?|sources?)\b[^.]{0,60}?"
    r"\b(?:share|provide)\b",
    _I,
)

# A chart drawn over nothing (run1 #1: "With the current dataset empty, no bars appear").
EMPTY_CHART = re.compile(
    r"\b(?:data ?set|data) (?:is )?empty\b|\bno bars\b|\bempty (?:chart|plot)\b", _I
)
INVENTORY_DUMP = re.compile(r"^Here is what \*\*[^*]+\*\* has, counted live", _I)
# A question about what can be known of one person (run1 #57 "Can my manager see when I
# badge in and out?" answered "Yes"). Flag only; the PDP decides what is allowed.
INDIVIDUAL_Q = re.compile(
    r"\b(?:see|track|monitor|know|tell|find out|check)\b[^?]{0,30}?\b(?:when|where|whether|if"
    r"|who)\b[^?]{0,20}?\b(?:I|me|someone|a person|he|she|my colleague)\b",
    _I,
)

# System-authored "no answer was built" templates (grepped from orchestrator/, and each seen
# in the runs). Checked BEFORE the decline markers because their own wording contains
# decline-like phrases ("not a statement that the building has no such data").
INCOMPLETE_TEMPLATES = [
    ("could_not_put_together", re.compile(r"could not put an answer together", _I)),
    ("could_not_generate", re.compile(r"could(?:n't| not) generate a response", _I)),
    ("too_long", re.compile(r"took too long to process", _I)),
    ("existence_check_timeout", re.compile(r"existence check didn't complete", _I)),
    ("cannot_complete_as_asked", re.compile(r"can't complete that request as asked", _I)),
    ("fetch_budget", re.compile(r"more than I can read", _I)),
    ("cannot_rank", re.compile(r"couldn't rank any spaces", _I)),
    ("gap_on_my_side", re.compile(r"gap on my side", _I)),
    ("compare_needs_zone", re.compile(r"requires sensors with linked time-series data", _I)),
]
ROOM_NAME_CLARIFY = re.compile(r"couldn't match that room name", _I)

# Deterministic refusals and absences produced by policy code, not by a model.
TEMPLATE_DECLINES = [
    ("privacy_policy", re.compile(r"\bI can't answer that\.|_Policy: `policy_", _I)),
    ("no_prior_turn", re.compile(r"haven't said anything earlier|nothing to follow up on", _I)),
    ("not_on_record", re.compile(r"I don't have that specific information on record", _I)),
    ("no_measured_series", re.compile(r"\bI have no measured series\b", _I)),
    ("not_measured_here", re.compile(r"\bis not measured in\b", _I)),
    ("documents_do_not_answer", re.compile(r"documents do not answer this", _I)),
]
# The referent gate is known to over-extract ("'brief corridor' does not exist"), so its
# refusal is an honest decline only at LOW confidence.
REFERENT_ABSENT = re.compile(r"'([^']{2,60})' does not exist in this building", _I)

DECLINE_MARKERS = [
    re.compile(
        r"\b(?:do|does|did)(?:n't| not) (?:contain|include|record|indicate|hold|store|list"
        r"|show|provide|mention|capture|specify|cover|have)\b",
        _I,
    ),
    re.compile(
        r"\b(?:cannot|can't|can not|unable to|could not|couldn't) (?:be )?(?:determine"
        r"|identify|assess|confirm|say|tell|calculate|compute|rank|list|find|answer|verify"
        r"|evaluate|recommend)",
        _I,
    ),
    re.compile(
        r"\bnot (?:measured|recorded|captured|available|held|present|stored|tracked|listed"
        r"|included|contained|documented)\b",
        _I,
    ),
    re.compile(r"\bthere is no (?:record|information|data|documented)\b", _I),
    re.compile(
        r"\bnone of (?:them|these|the records|the records?|the entries)\b[^.]{0,20}?"
        r"\b(?:contain|include|record|provide|mention|indicate|show|list)",
        _I,
    ),
    re.compile(r"\bI(?:'m| am) (?:sorry|afraid)\b", _I),
    re.compile(r"\bthere are no results for\b", _I),
]
# "No record contains that term" opens a decline (run1 #19); "flagged as no-show (i.e., no
# evidence of use)" is DATA inside an answer (run1 #26), as is "no evidence" in an answer to
# "which matters lack evidence" (run2 #4). So: sentence-initial only, and ignored when its
# noun is what the question asks about.
NO_NOUN = re.compile(
    r"(?:^|[.!?]\s+)(?:there (?:is|are) )?no (record|information|data|evidence|mention|details?"
    r"|documentation)\b",
    _I,
)

# What a decline says the store DOES hold -- used to tell a decline from the right register
# from a decline read off an unrelated one ("They record operating regimes for HVAC" for a
# shared-desk question; "contains information only about Waste Collection Points" for a
# barometric meter).
CONTENTS_RES = [
    re.compile(
        r"\b(?:they|these records|the records|this register|the building's data|the data"
        r"|the (?:building )?ontology(?: data)?(?: you provided)?)\s+(?:only\s+|do\s+|does\s+)?"
        r"(?:record|records|contain|contains|list|lists|describe|describes|capture|captures"
        r"|provide|provides|include|includes)\s+(?:only\s+)?(?:information\s+)?(?:only\s+)?"
        r"(?:about\s+|on\s+)?(?P<c>[^.\n]{3,200})",
        _I,
    ),
    re.compile(r"\bdata (?:is|are) (?:only |about )+(?P<c>[^.\n]{3,160})", _I),
    re.compile(
        r"\bwhat (?:they|the records|it) do(?:es)? (?:record|capture|contain|show|provide)"
        r"(?: is)?:?\s*(?P<c>.{3,300})",
        _I | re.S,
    ),
    re.compile(r"\bregister:\s*(?P<c>[^|\n]{3,60})"),
    re.compile(r"\bsearched (?P<c>[^;.\n]{3,80})", _I),
]
REGISTER_COUNT = re.compile(
    r"\b\d+\s+(?P<c>(?:[a-z/-]+\s){0,3}[a-z/-]+?)\s+(?:records|entries)\b", _I
)

CAPABILITY_DUMP = re.compile(r"^Here is what I found for\b", _I)
RAW_RECORD_DUMP = re.compile(r"^Found \d+ result\(s\):", _I)
SPATIAL_LISTING = re.compile(r"^##\s+(?P<t>[^\n]+)\n+\*\*\d+\*\*\s+space\(s\) found", _I)
REPORT_LOGGED = re.compile(r"has been logged as \*\*[A-Z]+-\d+", _I)
CONTROL_QUEUED = re.compile(r"Command queued for approval", _I)

PRIOR_TURN_Q = re.compile(
    r"\b(?:you (?:mentioned|said|told me|showed)|earlier|last time|as (?:you|we) discussed)\b",
    _I,
)
PROXY_SENSOR_COUNT = re.compile(
    r"\b(?:sensor[ -]count|number of sensors|(?:fewest|fewer|most|lowest|highest|smallest)"
    r" (?:number of )?sensors)\b",
    _I,
)
PROXY_INFERENCE = re.compile(
    r"\b(?:likely|suggest\w*|indicat\w*|usually means|therefore|vulnerab\w*|fragil\w*|busy"
    r"|demand|activity|quiet\w*|calm)\b",
    _I,
)
ASSUMED_FILL = re.compile(
    r"\bnot (?:listed|recorded|specified|available|stated)\b[^.\n]{0,40}\bbut\b[^.\n]{0,60}"
    r"\b(?:typical(?:ly)?|usually|probably|assum\w*)\b",
    _I,
)
QUANTITY_Q = re.compile(
    r"\b(?:how many|how much|hours?|kwh|percentage|per ?cent|average|count|total)\b", _I
)
BOLD_FIGURE = re.compile(r"\*\*[^*\n]*\d[^*\n]*\*\*")
RECORD_ID = re.compile(r"\b[A-Z]{2,5}-\d{2,}\b")
USER_SUPPLIED = re.compile(
    r"\b(?:you (?:provided|supplied|shared|pulled back|gave)|(?:data|records|results) you"
    r" (?:provided|have|pulled))\b",
    _I,
)
# Phase 0 (2026-09-17): register summaries open "The room holds 32 records in total" for a
# washroom, an impairment and a server-room question. A flag, not a bucket: the answer that
# follows can still be right (phase0 row 45).
ROOM_HOLDS_RECORDS = re.compile(r"^The room holds \*{0,2}\d+ records", _I)
SAYS_SIMULATED = re.compile(r"\bsimulated\b|isSimulated", _I)
BOUNDARY_REFUSES = re.compile(
    r"\b(?:do not|must not|never|withh[eo]ld|not a valid|mark the result|ask for clarification"
    r"|confirmed facts only)\b",
    _I,
)

ACTION_VERBS = (
    "book",
    "reserve",
    "order",
    "send",
    "email",
    "call",
    "open",
    "close",
    "unlock",
    "lock",
    "turn",
    "switch",
    "set",
    "schedule",
    "plan",
    "cancel",
    "buy",
    "arrange",
)
_ACTION_Q = re.compile(
    r"^(?:(?:can|could|would|will) you (?:please )?)?(?:please )?(?:"
    + "|".join(ACTION_VERBS)
    + r")\b",
    _I,
)
_WH_START = re.compile(
    r"^(?:which|what|where|when|who|whom|whose|why|how|is|are|was|were|do|does|did|has|have"
    r"|can|could|should|would|will)\b",
    _I,
)

# Generic building modalities (not one building's names) for matching source chips.
MODALITIES: Dict[str, Tuple[str, ...]] = {
    "energy": (
        "energy",
        "electric",
        "power",
        "kwh",
        "meter",
        "consumption",
        "tariff",
        "battery",
        "solar",
        "carbon",
        "submeter",
    ),
    "water": ("water", "flow", "leak", "drain", "plumbing", "tap"),
    "occupancy": (
        "occupancy",
        "occupied",
        "people",
        "footfall",
        "crowd",
        "busy",
        "pir",
        "presence",
        "headcount",
        "traffic",
        "utilisation",
        "utilization",
    ),
    "temperature": (
        "temperature",
        "warm",
        "hot",
        "cold",
        "cool",
        "heating",
        "thermal",
        "overheat",
        "comfort",
        "delta",
    ),
    "air": ("co2", "air", "ventilat", "stuffy", "pm2", "voc", "humidity"),
    "noise": ("noise", "quiet", "loud", "acoustic", "sound"),
    "light": ("light", "daylight", "illuminance", "lux", "glare"),
    "equipment": (
        "ahu",
        "plant",
        "fan",
        "pump",
        "chiller",
        "boiler",
        "hvac",
        "runtime",
        "equipment",
        "damper",
        "valve",
    ),
}
_COMPATIBLE = {
    "equipment": {"temperature", "air", "energy"},
    "temperature": {"equipment"},
    "air": {"equipment"},
    "energy": {"equipment"},
}

_ORDINALS = {
    "ground": 0,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}


def modalities(text: str) -> Set[str]:
    low = normalise(text).lower()
    return {
        m
        for m, words in MODALITIES.items()
        if any(re.search(r"\b" + re.escape(w), low) for w in words)
    }


def floors_named(text: str) -> Set[int]:
    """Floors named by an explicit label only -- never a bare number (BUG-191)."""
    low = normalise(text).lower()
    out: Set[int] = set()
    for m in re.finditer(r"\b(?:floor|level)\s*[-_]?\s*(\d{1,2})\b", low):
        out.add(int(m.group(1)))
    for m in re.finditer(
        r"\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth"
        r"|\d{1,2}(?:st|nd|rd|th))[\s-]+floor\b",
        low,
    ):
        tok = m.group(1)
        out.add(_ORDINALS[tok] if tok in _ORDINALS else int(re.match(r"\d+", tok).group(0)))
    for m in re.finditer(r"\b(?:room|rm|zone|space)\s*(\d{1,2})\.\d{2,3}\b", low):
        out.add(int(m.group(1)))
    return out


def rooms_named(text: str) -> Set[str]:
    low = normalise(text).lower()
    return {f"{int(a)}.{b}" for a, b in re.findall(r"\b(?:room|rm)\s*(\d{1,2})\.(\d{2,3})\b", low)}


def stated_contents(body: str) -> str:
    """What the answer says the store it read DOES hold (empty when it says nothing)."""
    parts = []
    for rx in CONTENTS_RES:
        for m in rx.finditer(body):
            parts.append(m.group("c"))
    for m in REGISTER_COUNT.finditer(body):
        parts.append(m.group("c"))
    return " | ".join(parts)


def is_interrogative(q: str) -> bool:
    q = q.strip()
    return bool(_WH_START.match(q)) or q.endswith("?")


def is_action_request(q: str) -> bool:
    return bool(_ACTION_Q.match(q.strip()))


# ─────────────────────────────────────────────────────────────────────────────────────────
# The grader
# ─────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Verdict:
    bucket: str
    confidence: str
    rule: str
    reason: str
    flags: List[str] = field(default_factory=list)


def _first(rules: Sequence[Tuple[str, re.Pattern]], text: str) -> Optional[Tuple[str, re.Match]]:
    for name, rx in rules:
        m = rx.search(text)
        if m:
            return name, m
    return None


def grade(question: str, answer: str, status: str = "OK", boundary: str = "") -> Verdict:
    """One bucket for one answer. PRECEDENCE IS THE ORDER OF THE STEPS BELOW (first wins)."""
    p = split_answer(answer)
    body, q = p.body, normalise(question)
    flat = plain(body)
    flags: List[str] = []
    if USER_SUPPLIED.search(flat):
        flags.append("speaks_as_if_user_supplied_data")
    if SAYS_SIMULATED.search(p.raw):
        flags.append("says_simulated")
    if ROOM_HOLDS_RECORDS.search(body) and not re.search(r"\broom\b", q, _I):
        flags.append("register_summary_calls_it_a_room")
    footer_text = "\n".join(p.footers)
    remediation_footer = FOOTER_REMEDIATION.search(footer_text) or FOOTER_REMEDIATION.search(body)
    if remediation_footer:
        flags.append("remediation_footer")
    q_stems = content_stems(q)
    boundary_refuses = BOUNDARY_REFUSES.search(boundary or "")
    boundary_note = "; consistent with the catalogue boundary" if boundary_refuses else ""

    def v(bucket: str, conf: str, rule: str, reason: str) -> Verdict:
        return Verdict(bucket, conf, rule, reason, flags)

    # 1. Nothing to read. A transport failure is not a behavioural verdict (lessons #69), so
    #    it is INCOMPLETE with the status named, and the report counts it separately.
    st = (status or "").strip().upper()
    if st and not st.startswith("OK"):
        return v(INCOMPLETE, HIGH, "transport", f"status {status!r}, not an answer")
    if not body:
        return v(INCOMPLETE, HIGH, "empty", "empty answer after removing footers")

    lead = lead_text(body)
    decline_lead = None
    for rx in DECLINE_MARKERS:
        decline_lead = rx.search(lead)
        if decline_lead:
            break
    if not decline_lead:
        nm = NO_NOUN.search(lead)
        if nm and not overlap(content_stems(nm.group(1)), q_stems):
            decline_lead = nm

    # 2. A strong add-data instruction wins over EVERYTHING that follows, including a decline
    #    and a non-answer: telling a stakeholder to upload a TTL or install a sensor is the
    #    thing that reads as broken whatever surrounds it, and the readiness goal names it.
    hit = _first(STRONG_ADD, flat)
    if hit:
        return v(
            ADD_DATA,
            HIGH,
            f"add.{hit[0]}",
            f"instructs the reader to add data: {_quote(flat, hit[1])}",
        )
    for m in INSTALL_SENSOR.finditer(flat):
        window = flat[max(0, m.start() - 100) : m.end() + 100]
        if decline_lead or INSTALL_FOR_DATA.search(window):
            return v(
                ADD_DATA,
                HIGH,
                "add.install_sensor",
                f"tells the reader to install sensors to get the answer: {_quote(flat, m)}",
            )

    # 3. System-authored non-answer templates. Before any decline check, because these
    #    templates themselves say things like "not a statement that the building has no data".
    hit = _first(INCOMPLETE_TEMPLATES, flat)
    if hit:
        conf, note = HIGH, ""
        if hit[0] in ("fetch_budget", "cannot_rank") and re.search(r"clarif", boundary or "", _I):
            conf = LOW
            note = " (the boundary permits a clarification; a human may call it a decline)"
        return v(
            INCOMPLETE,
            conf,
            f"incomplete.{hit[0]}",
            f"non-answer template: {_quote(flat, hit[1])}{note}",
        )
    m = ROOM_NAME_CLARIFY.search(flat)
    if m:
        conf = LOW if rooms_named(q) else HIGH
        return v(
            INCOMPLETE,
            conf,
            "incomplete.room_name_clarify",
            f"asks for a room id the question never mentioned: {_quote(flat, m)}",
        )
    m = EMPTY_CHART.search(flat)
    if m and "![" in body:
        return v(
            INCOMPLETE,
            HIGH,
            "incomplete.empty_chart",
            f"a chart drawn over no data: {_quote(flat, m)}",
        )

    # 4. Deterministic policy refusals and absences. These are the CORRECT outcome whatever
    #    lane produced them, so they are decided before any wrong-lane evidence is weighed.
    hit = _first(TEMPLATE_DECLINES, body)
    if hit:
        return v(
            HONEST_DECLINE,
            HIGH,
            f"decline.{hit[0]}",
            f"policy/absence template: {_quote(body, hit[1])}{boundary_note}",
        )
    m = REFERENT_ABSENT.search(flat)
    if m:
        return v(
            HONEST_DECLINE,
            LOW,
            "decline.referent_absent",
            f"referent gate refused {m.group(1)!r} — check it was a real place, not an "
            f"adjective the gate picked up: {_quote(flat, m)}",
        )

    # 5. High-confidence wrong lanes: the lane's own output shape contradicts the question.
    m = REPORT_LOGGED.search(body)
    if m and _WH_START.match(q.strip()):
        return v(
            WRONG_LANE,
            HIGH,
            "lane.report_intake",
            f"a question was logged as a maintenance report: {_quote(body, m)}",
        )
    m = CONTROL_QUEUED.search(body)
    if m and not is_action_request(q):
        return v(
            WRONG_LANE,
            HIGH,
            "lane.control",
            f"a question was queued as a control command: {_quote(body, m)}",
        )
    fq, fa = floors_named(q), floors_named(body)
    if fq and fa and not (fq & fa):
        return v(
            WRONG_LANE,
            HIGH,
            "lane.floor_mismatch",
            f"question names floor(s) {sorted(fq)}, answer only floor(s) {sorted(fa)}",
        )
    rq, ra = rooms_named(q), rooms_named(body)
    if rq and ra and not (rq & ra):
        return v(
            WRONG_LANE,
            LOW,
            "lane.room_mismatch",
            f"question names room(s) {sorted(rq)}, answer only {sorted(ra)[:6]}",
        )
    m = SPATIAL_LISTING.search(body)
    if m and not overlap(content_stems(m.group("t")), q_stems):
        return v(
            WRONG_LANE,
            HIGH,
            "lane.space_listing",
            f"a listing of '{m.group('t').strip()}' spaces for a question not about them",
        )

    # 6. INVENTED — conservative, always LOW: a flag for a human, never an assertion.
    if PRIOR_TURN_Q.search(q) and not decline_lead:
        return v(
            INVENTED,
            LOW,
            "invented.prior_turn",
            "question refers to an earlier turn that did not happen in this chat, and the "
            f"answer plays along: \"{' '.join(flat.split())[:90]}...\"",
        )
    if not re.search(r"\bsensor", q, _I):
        for para in flat.split("\n\n"):
            pm = PROXY_SENSOR_COUNT.search(para)
            if pm and PROXY_INFERENCE.search(para):
                return v(
                    INVENTED,
                    LOW,
                    "invented.sensor_count_proxy",
                    f"infers a property from how many sensors a space has: {_quote(para, pm)}",
                )
    m = ASSUMED_FILL.search(flat)
    if m:
        return v(
            INVENTED,
            LOW,
            "invented.assumed_fill",
            f"fills a value the records do not hold: {_quote(flat, m)}",
        )
    telemetry = [s for s in p.sources if modalities(s)]
    bold_figure = BOLD_FIGURE.search(body)
    if (
        bold_figure
        and not decline_lead
        and len(body) < 400
        and "|" not in body
        and not RECORD_ID.search(body)
        and not telemetry
        and QUANTITY_Q.search(q)
    ):
        # The one place a digit is looked at: as the CLAIM needing grounding, never as proof.
        return v(
            INVENTED,
            LOW,
            "invented.ungrounded_figure",
            "a bolded figure for a measured quantity with no record, table or telemetry "
            f"source behind it: {_quote(body, bold_figure)}",
        )

    # 7. Lower-confidence wrong lanes: a lookup dump, the source chips, or the answer's own
    #    statement of what it read, do not match the question.
    if RAW_RECORD_DUMP.search(body):
        regs = " ".join(re.findall(r"register:\s*([^|\n]+)", body))
        if regs and not overlap(content_stems(regs), q_stems):
            return v(
                WRONG_LANE,
                LOW,
                "lane.raw_dump_unrelated",
                f"unnarrated record dump from unrelated register(s): {regs[:80]!r}",
            )
        return v(
            INCOMPLETE,
            LOW,
            "incomplete.raw_dump",
            "records returned as a raw 'Found N result(s)' dump, never narrated",
        )
    if CAPABILITY_DUMP.search(body) or INVENTORY_DUMP.search(body):
        if INVENTORY_DUMP.search(body):
            heads = re.findall(r"^- \*\*([^*\n]+)\*\*", body, flags=re.M)
            kind = "class inventory"
        else:
            heads = re.findall(r"\*\*([^*\n]{3,90})\*\*", body)[1:]
            kind = "topic lookup"
        shared = overlap(content_stems(" ".join(heads)), q_stems)
        if is_action_request(q):
            return v(
                WRONG_LANE,
                LOW,
                "lane.lookup_for_action",
                f"an action request answered with a {kind} ({', '.join(heads[:3])})",
            )
        if not shared:
            return v(
                WRONG_LANE,
                LOW,
                "lane.lookup_unrelated",
                f"{kind} whose entries ({', '.join(heads[:3])}) share no word with the question",
            )
        return v(
            ANSWERED,
            LOW,
            "answered.lookup",
            f"{kind} sharing {sorted(shared)[:4]} with the question — may not answer it",
        )

    q_mod = modalities(q)
    q_mod_ext = set(q_mod)
    for mod in q_mod:
        q_mod_ext |= _COMPATIBLE.get(mod, set())
    chip_mods: Set[str] = set()
    for s in telemetry:
        chip_mods |= modalities(s)
    chip_mismatch = bool(chip_mods) and not (chip_mods & q_mod_ext)
    contents = stated_contents(flat)
    c_stems = content_stems(contents)
    contents_mismatch = bool(c_stems) and not overlap(c_stems, q_stems)

    if decline_lead:
        quoted = _quote(lead, decline_lead)
        # 7a. A decline justified by telemetry from another modality ("the building's data is
        #     only energy-meter readings" for a door question) was read off the wrong lane.
        #     A catalogue boundary that sanctions declining keeps it a decline (LOW, flagged).
        if chip_mismatch:
            if boundary_refuses:
                flags.append("decline_cites_unrelated_source")
                return v(
                    HONEST_DECLINE,
                    LOW,
                    "decline.unrelated_telemetry_boundary",
                    f"declines ({quoted}) from telemetry {telemetry}{boundary_note}",
                )
            return v(
                WRONG_LANE,
                LOW,
                "lane.decline_from_unrelated_telemetry",
                f"declines ({quoted}) after reading telemetry {telemetry} for a question "
                f"about {sorted(q_mod) or 'no measured quantity'}",
            )
        # 7b. A decline whose stated store shares no word with the question stays a decline:
        #     the evidence is only lexical (run 2 row 42 said "they record the current fill
        #     percentage" for "bins always full" -- related, zero shared words). Flagged LOW.
        if contents_mismatch:
            flags.append("decline_cites_unrelated_source")
            return v(
                HONEST_DECLINE,
                LOW,
                "decline.unrelated_store",
                f"declines ({quoted}) but says it read {contents[:90]!r}{boundary_note}",
            )
        # 8. Honest decline, possibly carrying a weaker add-data nudge. A decline plus an
        #    instruction reads as broken, so the nudge promotes it (LOW: the nudge is weak).
        if remediation_footer:
            return v(
                ADD_DATA,
                LOW,
                "add.footer_on_decline",
                f"decline ({quoted}) with a remediation footer "
                f"{_quote(footer_text or body, remediation_footer)}",
            )
        sm = SOFT_ASK.search(flat)
        if sm:
            return v(
                ADD_DATA,
                LOW,
                "add.soft_ask_on_decline",
                f"decline that asks the reader to supply data: {_quote(flat, sm)}",
            )
        partial = len(body) > 900 or len(RECORD_ID.findall(body)) >= 3
        extra = " (substantial body: may be a partial answer)" if partial else ""
        return v(
            HONEST_DECLINE,
            LOW if partial else HIGH,
            "decline.lead",
            f"opens by declining: {quoted}{extra}{boundary_note}",
        )

    if chip_mismatch:
        return v(
            WRONG_LANE,
            LOW,
            "lane.source_modality",
            f"answer drawn from {telemetry} for a question about "
            f"{sorted(q_mod) or 'no measured quantity'}",
        )
    shared = overlap(content_stems(flat), q_stems)
    frac = len(shared) / max(1, len(q_stems))
    # For an ANSWER (not a decline) the named store must be unrelated AND the answer as a
    # whole must barely touch the question: run 3 row 42 answered "bins on floor 2" from the
    # "waste-collection" register -- a synonym, zero shared words, and a correct answer.
    if contents_mismatch and len(c_stems) >= 2 and frac < 0.2:
        return v(
            WRONG_LANE,
            LOW,
            "lane.register_unrelated",
            f"answer built from a store unrelated to the question: {contents[:90]!r}",
        )

    # 9. ANSWERED. Confidence rests on topical overlap and visible grounding -- never digits.
    grounded = bool(
        p.sources
        or RECORD_ID.search(body)
        or "|" in body
        or re.search(r"\b(?:records?|register|Best match)\b", flat, _I)
    )
    if len(flat) < 200 and frac < 0.25:
        return v(
            WRONG_LANE,
            LOW,
            "lane.short_unrelated",
            f"short answer sharing {sorted(shared) or 'nothing'} with the question",
        )
    if not grounded and not re.search(r"\b(?:building|floor|room|sensors?)\b", flat, _I):
        flags.append("general_knowledge_ungrounded")
        return v(
            ANSWERED,
            LOW,
            "answered.general_knowledge",
            "general-knowledge prose with no source, record or building reference",
        )
    m = re.search(r"\bdo(?:es)? not (?:contain|record|include)\b|\bnot recorded\b", flat, _I)
    if m:
        flags.append("partial_decline")
    individual = bool(INDIVIDUAL_Q.search(q))
    if individual:
        flags.append("answers_a_question_about_an_individual")
    conf = HIGH if (frac >= 0.15 and grounded and len(flat) >= 200 and not individual) else LOW
    return v(
        ANSWERED,
        conf,
        "answered",
        f"substantive answer sharing {sorted(shared)[:5]} with the question"
        + ("" if grounded else "; no visible grounding")
        + ("; the question is about what can be known of one person" if individual else "")
        + (f"; also declines part: {_quote(flat, m)}" if m else ""),
    )


# ─────────────────────────────────────────────────────────────────────────────────────────
# Report
# ─────────────────────────────────────────────────────────────────────────────────────────


def _pct(n: int, d: int) -> str:
    return f"{100.0 * n / d:.1f}%" if d else "—"


def grade_rows(rows: List[Dict], bank: Dict[str, Dict]) -> List[Dict]:
    out = []
    for i, r in enumerate(rows):
        key = _norm_q(r.get("q", ""))
        meta = bank.get(key, {})
        if bank and key not in bank:
            who = "(not in bank)"
        else:
            # v5 and survey rows legitimately carry no stakeholder; that is not a join miss.
            who = meta.get("stakeholder", "") or "(no stakeholder in bank)"
        verdict = grade(
            r.get("q", ""),
            r.get("answer", "") or "",
            r.get("status", "OK"),
            meta.get("boundary", ""),
        )
        out.append(
            {
                "row": i,
                "run": r.get("run"),
                "id": meta.get("id", ""),
                "stakeholder": who if bank else "",
                "category": meta.get("category", ""),
                "source": meta.get("source", ""),
                "question": r.get("q", ""),
                "status": r.get("status", ""),
                "secs": r.get("secs"),
                "bucket": verdict.bucket,
                "confidence": verdict.confidence,
                "rule": verdict.rule,
                "reason": verdict.reason,
                "flags": verdict.flags,
                "answer_head": " ".join((r.get("answer") or "").split())[:300],
            }
        )
    return out


def _breakdown(graded: List[Dict], key) -> List[str]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for g in graded:
        groups[key(g)].append(g)
    short = {
        ANSWERED: "answered",
        HONEST_DECLINE: "decline",
        ADD_DATA: "add-data",
        WRONG_LANE: "wrong lane",
        INCOMPLETE: "incomplete",
        INVENTED: "invented",
    }
    lines = [
        "| group | n | " + " | ".join(short[b] for b in BUCKETS) + " | weird |",
        "|---|---:|" + "---:|" * (len(BUCKETS) + 1),
    ]
    for name, sub in sorted(
        groups.items(),
        key=lambda kv: (-sum(1 for g in kv[1] if g["bucket"] in WEIRD) / len(kv[1]), kv[0]),
    ):
        c = Counter(g["bucket"] for g in sub)
        weird = sum(c[b] for b in WEIRD)
        lines.append(
            f"| {name[:60].replace('|', '/')} | {len(sub)} | "
            + " | ".join(str(c[b]) for b in BUCKETS)
            + f" | {_pct(weird, len(sub))} |"
        )
    return lines


def render_report(graded: List[Dict], input_note: str, bank_path: str) -> str:
    n = len(graded)
    c = Counter(g["bucket"] for g in graded)
    hi = Counter(g["bucket"] for g in graded if g["confidence"] == HIGH)
    transport = sum(1 for g in graded if g["rule"] == "transport")
    weird = sum(c[b] for b in WEIRD)
    L = [
        "# Stakeholder answer grades",
        "",
        f"- input: {input_note}",
        f"- bank: {bank_path or '(none — stakeholder/category unknown)'}",
        f"- rows: **{n}**; transport failures (status not OK): {transport}",
        "",
        "Grades describe the SHAPE of each answer, not whether its facts are true. INVENTED is "
        "only ever a low-confidence flag. An honest decline is a correct outcome, not a failure.",
        "",
        "| bucket | n | share | of which high confidence |",
        "|---|---:|---:|---:|",
    ]
    for b in BUCKETS:
        L.append(f"| {b} | {c[b]} | {_pct(c[b], n)} | {hi[b]} |")
    L += [
        "",
        f"**Weird** (add-data + wrong lane + incomplete + invented): **{weird} / {n} = "
        f"{_pct(weird, n)}**; high-confidence only: "
        f"{sum(hi[b] for b in WEIRD)} / {n} = {_pct(sum(hi[b] for b in WEIRD), n)}.",
        "",
    ]
    flags = Counter(f for g in graded for f in g["flags"])
    if flags:
        L += ["| flag (does not change the bucket) | rows |", "|---|---:|"]
        L += [f"| {f} | {k} |" for f, k in flags.most_common()]
        L.append("")
    rules = Counter(g["rule"] for g in graded)
    L += [
        "<details><summary>Rules that decided the grades</summary>",
        "",
        "| rule | rows |",
        "|---|---:|",
    ]
    L += [f"| {r} | {k} |" for r, k in rules.most_common()]
    L += ["", "</details>", "", "## Per stakeholder role", ""]
    L += _breakdown(graded, lambda g: g["stakeholder"] or "(unknown)")
    L += [
        "",
        "## Per category",
        "",
        "Catalogue rows carry no category; they are grouped under their source.",
        "",
    ]
    L += _breakdown(graded, lambda g: g["category"] or f"({g['source'] or 'unknown'})")
    L += ["", "## Every weird answer", ""]
    for g in graded:
        if g["bucket"] not in WEIRD:
            continue
        L += [
            f"### {g['id'] or '#' + str(g['row'])} — {g['bucket']} ({g['confidence']})",
            "",
            f"**Q:** {g['question']}",
            "",
            f"- stakeholder: {g['stakeholder'] or '—'}",
            f"- rule: `{g['rule']}` — {g['reason']}",
            f"- flags: {', '.join(g['flags']) or '—'}",
            "",
            "```",
            g["answer_head"].replace("```", "'''"),
            "```",
            "",
        ]
    L += [
        "## Low-confidence verdicts — read these",
        "",
        "| row | id | bucket | rule | reason | question |",
        "|---:|---|---|---|---|---|",
    ]
    for g in graded:
        if g["confidence"] == LOW:
            L.append(
                f"| {g['row']} | {g['id']} | {g['bucket']} | `{g['rule']}` | "
                f"{g['reason'][:160].replace('|', '/')} | "
                f"{g['question'][:90].replace('|', '/')} |"
            )
    return "\n".join(L) + "\n"


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("input", help="ask_questions.py --out report (.md) or its .md.jsonl")
    ap.add_argument("--bank", default="", help="bank jsonl (build_stakeholder_bank.py)")
    ap.add_argument("--out", required=True, help="output prefix; writes <out>.md and <out>.jsonl")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # nosec B110 - console encoding is best effort
            pass

    inp = Path(args.input)
    if not inp.exists() and not inp.with_name(inp.name + ".jsonl").exists():
        print(f"not found: {inp}")
        return 2
    rows, note = load_answers(inp)
    bank = load_bank(Path(args.bank)) if args.bank else {}
    graded = grade_rows(rows, bank)
    if bank:
        missing = sum(1 for g in graded if g["stakeholder"] == "(not in bank)")
        if missing:
            note += f"; {missing} question(s) not found in the bank"

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    md_path, jsonl_path = Path(str(out) + ".md"), Path(str(out) + ".jsonl")
    md_path.write_text(render_report(graded, note, args.bank), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(g, ensure_ascii=False) for g in graded) + "\n", encoding="utf-8"
    )
    c = Counter(g["bucket"] for g in graded)
    print(note)
    for b in BUCKETS:
        print(f"{b:22s} {c[b]:4d}  {_pct(c[b], len(graded))}")
    print(f"low confidence: {sum(1 for g in graded if g['confidence'] == LOW)}")
    print(f"[written] {md_path}\n[written] {jsonl_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
