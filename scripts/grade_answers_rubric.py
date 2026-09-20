#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rubric grader for recorded answers, calibrated against human labels.

WHY THIS EXISTS
---------------
``scripts/grade_stakeholder_answers.py`` scored 20 of 147 recorded answers "weird"; two
careful hand reads of the same answers scored 107 and 113. Every claim of the form "this
change improved things" in this project is downstream of that instrument, so the instrument
has to be measured before it is used. This module does three things:

1. **Scores one recorded answer on explicit rubric dimensions** (see ``Dimension``), and
   collapses them into a single verdict comparable to the human's three
   (``GOOD_ANSWER`` / ``GOOD_DECLINE`` / ``WEIRD``), with the dimension scores and a
   one-line reason kept alongside.
2. **Offers two backends behind one interface** -- ``--judge deterministic`` (features only,
   no model, no network) and ``--judge llm`` (a structured-output judge that must return a
   JSON object matching a schema; an unparseable reply is ``UNGRADED``, never guessed).
3. **Calibrates**: over the 294 hand-labelled rows in ``docs/phase0`` it reports Cohen's
   kappa and a confusion matrix per split and overall, for the old heuristic, the
   deterministic judge and the LLM judge, plus precision/recall on the WEIRD class --
   the class the old grader misses.

A grader that does not beat the old heuristic's kappa is reported as such. Nothing here
decides that a grader is good; it only measures agreement with the human labels, which are
treated as ground truth.

OFFLINE
-------
Everything except ``--judge llm`` runs with no network and no live system. ``--gate`` grades
recorded answers only and never asks the running stack.

USAGE
-----
    # Calibration over the 294 labelled rows (deterministic + old heuristic; no GPU)
    python scripts/grade_answers_rubric.py --calibrate --out docs/phase0/rubric_calibration

    # Add an LLM-judge column, smoke size (a GPU slot is needed for the full 294)
    python scripts/grade_answers_rubric.py --calibrate --with-llm --llm-limit 20

    # Grade one recorded run
    python scripts/grade_answers_rubric.py --grade docs/phase0/phase0_rerun.md.jsonl \
        --bank docs/phase0/phase0_bank.jsonl --out scripts/outputs/rubric_rerun

    # Regression gate: exits non-zero when the weird share rises
    python scripts/grade_answers_rubric.py --gate new_run.md.jsonl --baseline old_run.md.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent

# ─────────────────────────────────────────────────────────────────────────────────────────
# Verdicts and dimensions
# ─────────────────────────────────────────────────────────────────────────────────────────

GOOD_ANSWER = "GOOD_ANSWER"
GOOD_DECLINE = "GOOD_DECLINE"
WEIRD = "WEIRD"
UNGRADED = "UNGRADED"
VERDICTS = (GOOD_ANSWER, GOOD_DECLINE, WEIRD)

PASS, FAIL, NA = "PASS", "FAIL", "NA"

# The rubric. Each dimension is one question a reader can answer from the recorded answer
# alone; none of them requires the live system.
DIMENSIONS: Tuple[Tuple[str, str], ...] = (
    (
        "answers_question",
        "Does it answer what was asked, rather than apologise, template or narrow?",
    ),
    (
        "figures_traceable",
        "Is every figure it states traceable to something the answer itself names?",
    ),
    (
        "honest_absence",
        "If it states an absence, is that absence stated honestly and about the right thing?",
    ),
    ("no_invented_claim", "Is it free of claims the cited evidence cannot support?"),
    ("right_subject", "Is the whole answer about the subject that was asked about?"),
)
DIMENSION_NAMES = tuple(name for name, _ in DIMENSIONS)


@dataclass
class Signal:
    """One observed defect: which rubric dimension it fails and the text that shows it."""

    code: str
    dimension: str
    evidence: str

    def as_dict(self) -> Dict[str, str]:
        return {"code": self.code, "dimension": self.dimension, "evidence": self.evidence}


@dataclass
class RubricResult:
    verdict: str
    dimensions: Dict[str, str]
    reason: str
    signals: List[Signal] = field(default_factory=list)
    judge: str = "deterministic"
    confidence: str = "med"

    def as_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict,
            "judge": self.judge,
            "confidence": self.confidence,
            "dimensions": self.dimensions,
            "reason": self.reason,
            "signals": [s.as_dict() for s in self.signals],
        }


# ─────────────────────────────────────────────────────────────────────────────────────────
# Text normalisation
# ─────────────────────────────────────────────────────────────────────────────────────────

_SMART = {
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "‑": "-",
    "‒": "-",
    "–": "-",
    "—": "-",
    "−": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    "…": "...",
}


def normalise(text: str) -> str:
    """Fold typographic variants so one regex matches both renderings of a phrase."""
    out = text or ""
    for src, dst in _SMART.items():
        out = out.replace(src, dst)
    # Markdown emphasis inside a sentence hides phrases from a plain regex.
    out = re.sub(r"\*\*(.+?)\*\*", r"\1", out, flags=re.S)
    out = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", out, flags=re.S)
    return out


_RULE_SPLIT = re.compile(r"\n\s*-{3,}\s*\n")
_SUGGESTION_CUT = re.compile(r"You might also ask:", re.I)
_FURNITURE = re.compile(
    r"^\s*(?:\*?Sources?:|\*?From .{0,60}documents|_?Policy:|You might also ask)", re.I
)


def body_of(answer: str) -> str:
    """The answer without its trailing sources / follow-up furniture.

    A horizontal rule is NOT on its own a footer marker: several answers put their evidence
    table under one. Only trailing segments that are short and look like furniture are
    dropped, so a table below a rule is still part of the answer being graded.
    """
    text = _SUGGESTION_CUT.split(normalise(answer))[0]
    segments = _RULE_SPLIT.split(text)
    while len(segments) > 1:
        tail = segments[-1].strip()
        if tail and (len(tail) > 400 or not _FURNITURE.match(tail)):
            break
        segments.pop()
    return "\n".join(segments).strip()


_WORD = re.compile(r"[a-z][a-z0-9]*")

_STOP = set(
    """a an and are as at be been being but by can cannot could do does did for from had has have
    how i if in into is it its me my no not of on or our should so such that the their them then
    there these they this those to us was we were what when where which who whom why will with
    would you your yours each any all other some only now today please tell show give about must
    need needs want kind type per also more most least than very just still yet does record records
    recorded recording data information building buildings room rooms space spaces one two three
    """.split()
)


# A generic facilities vocabulary: tokens that name the same subject are folded to one
# concept so "bins" and "waste", or "seat" and "workspace", count as the same topic. No
# building's own names appear here, and none may be added -- it is domain vocabulary only.
_CONCEPT_GROUPS: Tuple[Tuple[str, ...], ...] = (
    (
        "book",
        "booking",
        "reservation",
        "reserve",
        "reserved",
        "bookable",
        "schedule",
        "scheduled",
        "timetable",
    ),
    ("waste", "bin", "skip", "compactor", "recycling", "refuse", "collection"),
    ("seat", "seating", "desk", "workspace", "workstation", "chair", "table"),
    ("route", "circulation", "wayfinding", "corridor", "path", "travel", "walking", "journey"),
    (
        "access",
        "permission",
        "badge",
        "entry",
        "door",
        "opening",
        "turnstile",
        "authorised",
        "authorisation",
    ),
    ("clean", "cleaning", "caretaking", "janitorial", "housekeeping"),
    ("compliance", "inspection", "audit", "check", "certificate", "regulatory"),
    ("cost", "budget", "price", "spend", "financial", "procurement", "invoice", "tariff"),
    ("incident", "emergency", "evacuation", "alarm", "fire", "hazard", "safety"),
    ("asset", "equipment", "plant", "machine", "unit", "device"),
    ("energy", "electricity", "power", "kwh", "consumption", "meter", "metered", "submeter"),
    ("temperature", "thermal", "heating", "cooling", "warm", "cold", "hvac", "setpoint"),
    ("air", "co2", "carbon", "dioxide", "ventilation", "airflow", "stuffy", "ppm"),
    ("light", "lighting", "illuminance", "daylight", "glare", "lux"),
    ("noise", "sound", "acoustic", "loud", "quiet", "db"),
    ("occupancy", "occupied", "unoccupied", "presence", "people", "headcount", "footfall"),
    ("lift", "elevator", "stair", "escalator", "vertical"),
    ("toilet", "washroom", "restroom", "wc", "sanitary"),
    ("water", "drinking", "potable", "tap", "drainage", "drain", "plumbing"),
    ("maintenance", "repair", "work", "order", "fault", "defect", "service", "servicing"),
    ("event", "conference", "seminar", "lecture", "session", "meeting", "class", "talk", "tour"),
    ("network", "connectivity", "wifi", "server", "network", "it", "comms"),
    ("av", "projector", "display", "screen", "microphone", "camera", "capture"),
    ("accessibility", "accessible", "stepfree", "mobility", "wheelchair", "inclusion"),
    ("evidence", "approval", "approved", "sign", "signoff", "attestation"),
    ("policy", "procedure", "rule", "standard", "guidance"),
    ("owner", "ownership", "accountable", "responsible", "role"),
)
_CONCEPT_OF: Dict[str, str] = {}
for _group in _CONCEPT_GROUPS:
    for _tok in _group:
        _CONCEPT_OF.setdefault(_tok, _group[0])


def _singular(tok: str) -> str:
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("ses") and len(tok) > 4:
        return tok[:-2]
    if tok.endswith("s") and not tok.endswith("ss") and len(tok) > 3:
        return tok[:-1]
    return tok


def content_words(text: str) -> set:
    """Content tokens, singularised and folded onto facilities concepts, for topic overlap."""
    out = set()
    for raw in _WORD.findall(normalise(text).lower()):
        if len(raw) < 2:
            continue
        tok = _singular(raw)
        if tok in _STOP or len(tok) < 3:
            continue
        out.add(_CONCEPT_OF.get(tok, tok))
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────
# Detectors
#
# Each returns Signals. The patterns are taken from the defect classes the human reader
# wrote up in docs/phase0/phase0_read.md, not invented here; the class id is in the code.
# ─────────────────────────────────────────────────────────────────────────────────────────

_ADD_DATA = [
    (r"\bupload (?:a|the) (?:ttl|file|dataset)", "upload a TTL"),
    (r"\byou can add it\b", "you can add it"),
    (r"\badd or update it\b", "add or update it"),
    (r"\badd [^.\n]{0,60}\bentit(?:y|ies)\b", "add entities"),
    (r"\bplease provide (?:it|them|the data)\b", "please provide it"),
    (r"\bfeel free to share\b", "feel free to share"),
    (r"\bif you have (?:additional|other|more) data\b", "if you have additional data"),
    (r"\bconsult other sources\b", "consult other sources"),
    (r"\binstall (?:a |an |dedicated |additional )?[a-z -]{0,30}sensors?\b", "install a sensor"),
    (r"\bdeploy a [a-z ]{0,30}(?:sensor|device|meter)\b", "deploy a device"),
    (r"\bassign [^.\n]{0,40}(?:measurement )?units\b", "assign units"),
    (r"\bdefine units\b", "define units"),
    (r"\bprovide (?:a|the|an) (?:ttl|ontology|rdf)\b", "provide an ontology"),
    (r"\bshare (?:them|it) with me\b", "share it with me"),
]

_ATTRIBUTION = [
    (
        r"\b(?:data|records|ontology|information|register)[^.\n]{0,45}\byou (?:provided|have|asked about|gave|supplied)\b",
        "attributes the building's own data to the reader",
    ),
    (r"\byou provided\b", "'you provided'"),
    (r"\bthe records you have\b", "'the records you have'"),
    (r"\bthe data you have\b", "'the data you have'"),
]

_PROVENANCE_LEAK = [
    (r"\bsimulated\b", "'simulated' surfaced to the reader"),
    (r"\bsynthetic\b", "'synthetic' surfaced to the reader"),
    (r"\bisSimulated\b", "raw provenance flag"),
]

_LANE_JARGON = [
    (r"\bontology lane\b", "names an internal lane"),
    (r"\btime-?series lane\b", "names an internal lane"),
    (r"\bsensed modality\b", "internal vocabulary"),
    (r"\btoo_few_points\b", "internal status token"),
    (r"\bplan_hash\b|\bcontributing_uuids\b|\bplan_fingerprint\b", "internal identifier"),
]

_NON_ANSWER = [
    (
        r"could not put an answer together|couldn'?t answer that (?:about [^.\n]{0,60})?from "
        r"[^.\n]{0,60}records",
        "apology template",
    ),
    (r"\bno data was retrieved\b", "no data retrieved"),
    (r"returned no rows\b", "returned no rows"),
    (r"couldn'?t map part of your request", "refused to map part of the request"),
    (r"couldn'?t verify [^.\n]{0,40}coverage", "coverage check returned as the answer"),
    (r"could not build a clean time series", "series build failure returned as the answer"),
    (r"couldn'?t render the chart", "chart failure surfaced as content"),
    (r"can'?t complete that request as asked", "request refused by a guard rewrite"),
    (r"more than i can read and summarise in one request", "fetch-budget refusal"),
    (r"i summarised the data above but", "partial-render apology"),
]

_FOOTER_MISFIRE = [
    (r"evidence time:\s*unknown", "'Evidence time: unknown' footer"),
    (r"boundary:\s*not declared", "'Boundary: not declared' footer"),
    (r"the space you chose", "recheck footer with no chosen space"),
    (r"\bswitch if:", "recheck footer"),
    (r"meterServes", "raw meter predicate in a footer"),
]

_INTERNAL_PREFIX = re.compile(r"\b(?:ontosage|s223)\s*:\s*[A-Za-z_]")
_SNAKE = re.compile(r"\b[a-z]{3,}_[a-z][a-z_]{2,}\b")
_UUIDISH = re.compile(r"\b[0-9a-f]{6,8}\s?-\s?[0-9a-f ]{3,6}-", re.I)
_MANGLED_ID = re.compile(r"\b[0-9a-f]{1,3} [0-9a-f]{3,5} [0-9a-f]{3,5}\b")

_DECLINE_PATTERNS = [
    r"do(?:es)? not (?:contain|record|include|indicate|provide|hold|show)",
    r"don'?t (?:contain|record|include|have)",
    r"\bno information about\b",
    r"\bi can'?t answer that\b",
    r"\bi couldn'?t identify\b",
    r"\bi don'?t have (?:that|the) (?:specific )?information\b",
    r"\bnothing to report\b",
    r"\bdo not answer this\b",
    r"\bnot recorded\b",
    r"\bi have no measured series\b",
    r"\bi'?m sorry, but\b",
]
_DECLINE_RE = re.compile("|".join(_DECLINE_PATTERNS), re.I)

_REGISTER_CLAUSE = re.compile(
    r"(?:they|the records|it|these records|the building'?s? (?:data|records))\s+"
    r"(?:only\s+|do\s+)?(?:record|contain|provide|hold|describe|list)s?\b(?P<what>[^.\n]{10,240})",
    re.I,
)

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_ABBR = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE_PATTERNS = [
    re.compile(r"\b(\d{1,2})\s+(" + _MONTHS + r"|" + _ABBR + r")\.?\s+(\d{4})\b", re.I),
    re.compile(r"\b(" + _MONTHS + r"|" + _ABBR + r")\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I),
    re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"),
]
_MONTH_NUM = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
# Only a prose claim that something is still to come. A table column headed "Next due" is
# not that claim, so tables are stripped before this runs and the cue must sit on the same
# line as the date.
_FUTURE_CUE = re.compile(
    r"\b(?:the next|next\s+\w+\s+is|upcoming|is scheduled for|are scheduled for|"
    r"is due to|will (?:be|take place|happen))\b[^.\n]{0,45}$",
    re.I,
)


def _month_num(token: str) -> Optional[int]:
    return _MONTH_NUM.get(token.lower()[:4].rstrip(".")) or _MONTH_NUM.get(token.lower()[:3])


def _find_dates(text: str) -> List[Tuple[int, date]]:
    """(end_offset, date) for every date literal we can read out of the text."""
    found: List[Tuple[int, date]] = []
    for pat in _DATE_PATTERNS:
        for m in pat.finditer(text):
            try:
                groups = m.groups()
                if pat is _DATE_PATTERNS[2]:
                    d = date(int(groups[0]), int(groups[1]), int(groups[2]))
                elif pat is _DATE_PATTERNS[0]:
                    mn = _month_num(groups[1])
                    d = date(int(groups[2]), mn, int(groups[0])) if mn else None
                else:
                    mn = _month_num(groups[0])
                    d = date(int(groups[2]), mn, int(groups[1])) if mn else None
            except (ValueError, TypeError):
                d = None
            if d:
                found.append((m.start(), d))
    return found


# A line that states a count and then introduces its own itemised list.
_LIST_TOTAL = re.compile(r"(\d{1,3})\s+(?:of them\s+)?[a-z][^.\n:|]{0,70}:\s*$", re.M | re.I)
_ITEM_LEADING = re.compile(r"^\s*[-*+•]\s*(\d{1,3})\s+(?![%°]|of\b)[a-z]", re.I)
_ITEM_TRAILING = re.compile(r"^\s*[-*+•]\s*[A-Za-z][^:|\n]{0,40}:\s*(\d{1,3})\b")


def _breakdown_mismatch(body: str) -> Optional[str]:
    """A stated count followed by its own itemised list that adds up to something else.

    Deliberately narrow. It fires only when a line states a count and ends in a colon, the
    lines under it are a bullet list whose items all carry a number in the same position,
    and those numbers sum to a different figure. "Confirmed: 11 / Provisional: 3 /
    Cancelled: 2" under "each of the 16 bookings:" sums correctly and must not fire.
    """
    lines = prose_only(body).splitlines()
    for idx, line in enumerate(lines):
        m = _LIST_TOTAL.search(line)
        if not m:
            continue
        total = int(m.group(1))
        if total < 2 or total > 400:
            continue
        leading, trailing = [], []
        for nxt in lines[idx + 1 : idx + 12]:
            if not nxt.strip():
                if leading or trailing:
                    break
                continue
            hit_l, hit_t = _ITEM_LEADING.match(nxt), _ITEM_TRAILING.match(nxt)
            if hit_l:
                leading.append(int(hit_l.group(1)))
            elif hit_t:
                trailing.append(int(hit_t.group(1)))
            else:
                break
        parts = leading if len(leading) >= 2 else trailing
        if len(parts) < 2:
            continue
        got = sum(parts)
        if got != total and got <= total * 3:
            return (
                f"'{line.strip()[:60]}' is itemised as "
                + " + ".join(str(p) for p in parts)
                + f" = {got}"
            )
    return None


_TABLE_ROW = re.compile(r"^\s*\|")
_SEPARATOR_ROW = re.compile(r"^\s*\|[\s|:-]+\|?\s*$")
_N_OF_M = re.compile(r"\b(\d{1,3})\s+of\s+the\s+(\d{1,3})\s+([a-z][a-z -]{2,25})\b", re.I)


def _table_count_mismatch(body: str) -> Optional[str]:
    """A "N of the M <things>" claim above a single table that lists neither N nor M rows."""
    m = _N_OF_M.search(body)
    if not m:
        return None
    rows = 0
    started = False
    for line in body[m.end() :].splitlines():
        if _TABLE_ROW.match(line):
            started = True
            if not _SEPARATOR_ROW.match(line):
                rows += 1
        elif started:
            break
    if rows < 3:
        return None
    rows -= 1  # the header row
    claimed = (int(m.group(1)), int(m.group(2)))
    if rows not in claimed:
        return f"'{m.group(0)}' sits above a table of {rows} rows"
    return None


_BUILDING_SUBJECT = re.compile(
    r"\b(?:building|floor|room|corridor|lift|elevator|desk|office|lab|laborator\w*|toilet|washroom|"
    r"entrance|door|window|car ?park|reception|atrium|bin|waste|boiler|chiller|ahu|fan|pump|valve|"
    r"meter|sensor|hvac|heating|cooling|ventilation|lighting|occupan\w*|booking|book a|record|"
    r"register|asset|work order|maintenance|cleaning|energy|electricity|water|drain|circuit|"
    r"setpoint|plant|zone|space|site|campus|here|this site)\b",
    re.I,
)
_BUILDING_CITATION = re.compile(
    r"\b(?:the building|this building|the building'?s|floor \d|room \d|record|register|sensor|"
    r"[A-Z]{2,4}-\d{2,4})\b"
)


def _asks_about_a_building(question: str) -> bool:
    return bool(_BUILDING_SUBJECT.search(question or ""))


def _cites_the_building(body: str) -> bool:
    return bool(_BUILDING_CITATION.search(body or "")) or "|" in body


def _match_all(text: str, patterns: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    hits = []
    for pat, label in patterns:
        m = re.search(pat, text, re.I)
        if m:
            hits.append((label, m.group(0)[:90]))
    return hits


def prose_only(text: str) -> str:
    """The answer minus its markdown tables. A table legitimately repeats cell wording and
    legitimately carries date column headers; prose that does either is a defect."""
    keep = [ln for ln in text.splitlines() if not ln.lstrip().startswith("|")]
    return "\n".join(keep)


def _repeated_ngram(text: str, n: int = 8, floor: int = 5) -> Optional[Tuple[str, int]]:
    words = re.findall(r"\S+", prose_only(text))
    if len(words) < n * floor:
        return None
    counts = Counter(" ".join(words[i : i + n]) for i in range(len(words) - n + 1))
    gram, count = counts.most_common(1)[0]
    return (gram, count) if count >= floor else None


def detect_signals(
    question: str,
    answer: str,
    *,
    boundary: str = "",
    asof: Optional[date] = None,
    disabled: frozenset = frozenset(),
) -> List[Signal]:
    """Every rubric failure the recorded text alone can show.

    ``disabled`` drops named signal codes, so the calibration can report what each rule is
    worth on its own rather than asserting that all of them earn their place.
    """
    text = normalise(answer)
    body = body_of(answer)
    low = text.lower()
    signals: List[Signal] = []

    def add(code: str, dimension: str, evidence: str) -> None:
        if code in disabled:
            return
        signals.append(Signal(code, dimension, evidence[:160]))

    # C4/C18 -- tells the reader to supply data instead of answering.
    for label, quote in _match_all(text, _ADD_DATA):
        add("ADD_DATA_INSTRUCTION", "answers_question", f"{label}: '{quote}'")
        break

    # C3 -- the building's own data attributed to the reader.
    for label, quote in _match_all(text, _ATTRIBUTION):
        add("USER_ATTRIBUTION", "honest_absence", f"{label}: '{quote}'")
        break

    # C3 -- provenance vocabulary that must never reach a reader.
    for label, quote in _match_all(text, _PROVENANCE_LEAK):
        add("PROVENANCE_LEAK", "right_subject", f"{label}: '{quote}'")
        break

    # C5/C13 -- internal lane vocabulary as the answer.
    for label, quote in _match_all(text, _LANE_JARGON):
        add("LANE_JARGON", "answers_question", f"{label}: '{quote}'")
        break

    # C2/C5/C13/C14/C17 -- a template where an answer should be.
    for label, quote in _match_all(text, _NON_ANSWER):
        add("NON_ANSWER_TEMPLATE", "answers_question", f"{label}: '{quote}'")
        break

    # C6a -- footers describing something other than this answer.
    for label, quote in _match_all(text, _FOOTER_MISFIRE):
        add("FOOTER_MISFIRE", "right_subject", f"{label}: '{quote}'")
        break

    # C3/C16 -- raw identifiers and internal tokens rendered as content.
    snake = [s for s in _SNAKE.findall(body) if s not in {"step_free"}]
    if len(set(snake)) >= 2:
        add(
            "INTERNAL_TOKEN",
            "answers_question",
            "snake_case tokens: " + ", ".join(sorted(set(snake))[:4]),
        )
    elif _INTERNAL_PREFIX.search(body):
        add("INTERNAL_TOKEN", "answers_question", "ontology prefix token rendered to the reader")
    elif _UUIDISH.search(body) or _MANGLED_ID.search(body):
        add("INTERNAL_TOKEN", "answers_question", "raw identifier rendered as a place or name")

    # C3 -- runaway repetition.
    rep = _repeated_ngram(body)
    if rep:
        add("REPETITION", "answers_question", f"phrase repeated {rep[1]}x: '{rep[0][:60]}'")

    # C10 -- a bare fragment as the whole answer.
    words = re.findall(r"[A-Za-z0-9][\w'-]*", body)
    if len(words) < 15 and not _DECLINE_RE.search(body):
        add("FRAGMENT", "answers_question", f"whole answer is {len(words)} words: '{body[:80]}'")

    # C7 -- an internal contradiction the text itself exposes.
    for m in re.finditer(r"\b(\d{1,4})\s+of\s+(?:the\s+)?(\d{1,4})\b", body):
        a_n, b_n = int(m.group(1)), int(m.group(2))
        if a_n > b_n:
            add(
                "COUNT_CONTRADICTION",
                "figures_traceable",
                f"'{m.group(0)}' states a part larger than its whole",
            )
            break

    # C7 -- a breakdown that does not add up to the total it is a breakdown of.
    mismatch = _breakdown_mismatch(body)
    if mismatch:
        add("BREAKDOWN_SUM", "figures_traceable", mismatch)

    # C7 -- a headline count that the answer's own table does not show.
    table_gap = _table_count_mismatch(body)
    if table_gap:
        add("TABLE_COUNT_MISMATCH", "figures_traceable", table_gap)

    # C11 -- the document lane used as a catch-all for whatever it was handed.
    if re.search(r"documents do not answer this|i searched [^.\n]{0,80}register", low):
        add("DOCUMENT_CATCHALL", "answers_question", "document lane returned its catch-all decline")

    # C4 -- the answer names its own ontology as the thing that is missing data.
    m_ont = re.search(
        r"\b(?:the |this |your )?(?:provided |current |building )*ontology\b", body, re.I
    )
    if m_ont:
        add(
            "ONTOLOGY_NAMED",
            "honest_absence",
            f"names the ontology to the reader: '{m_ont.group(0)}'",
        )

    # C20 -- a descriptive phrase asserted not to exist as if it were a named place.
    m_ne = re.search(
        r"['\"]([^'\"\n]{3,40})['\"]\s+(?:does not exist|is not (?:a )?(?:known|recorded))",
        body,
        re.I,
    )
    if m_ne and not re.search(r"\d", m_ne.group(1)):
        add(
            "PHRASE_NOT_A_PLACE",
            "right_subject",
            f"'{m_ne.group(1)}' treated as a named place and declared absent",
        )

    # C6b -- a deictic space referent bound to an arbitrary point instead of clarified.
    if re.search(
        r"\b(?:this|the) (?:room|desk|space|office|area)\b|\bin here\b|\bright here\b",
        question,
        re.I,
    ) and not re.search(r"\b\d\.\d{2}\b", question):
        if re.search(r"\b(?:installed-node|node)\s*\d\.\d{2}\b", body, re.I):
            add(
                "DEICTIC_BOUND",
                "right_subject",
                "a deictic referent was bound to one named point without asking which",
            )

    # C7 -- a date in the past presented as the next/upcoming one.
    prose = prose_only(body)
    if asof is not None:
        for start, when in _find_dates(prose):
            if when < asof and _FUTURE_CUE.search(prose[max(0, start - 70) : start]):
                add(
                    "STALE_FUTURE_DATE",
                    "figures_traceable",
                    f"{when.isoformat()} is before {asof.isoformat()} but is offered as forthcoming",
                )
                break

    # C8 -- declines while quoting a register that has nothing to do with the question.
    if _DECLINE_RE.search(body):
        m = _REGISTER_CLAUSE.search(body)
        if m:
            described = content_words(m.group("what"))
            asked = content_words(question)
            if described and asked and not (described & asked):
                add(
                    "UNRELATED_REGISTER",
                    "right_subject",
                    "decline cites a register sharing no term with the question: "
                    + m.group("what").strip()[:90],
                )

    # C12 -- a question this building cannot be the source for, answered as general prose.
    if (
        not _asks_about_a_building(question)
        and not _cites_the_building(body)
        and len(words) > 60
        and not _DECLINE_RE.search(body)
    ):
        add(
            "OPEN_DOMAIN_PROSE",
            "no_invented_claim",
            "general prose with nothing from the building in it",
        )

    return signals


def is_decline(answer: str) -> bool:
    return bool(_DECLINE_RE.search(body_of(answer)))


# ─────────────────────────────────────────────────────────────────────────────────────────
# Judge interface + deterministic backend
# ─────────────────────────────────────────────────────────────────────────────────────────


class Judge:
    """One recorded answer in, one RubricResult out. No judge may touch the live system."""

    name = "judge"

    def grade(
        self, question: str, answer: str, *, boundary: str = "", asof: Optional[date] = None
    ) -> RubricResult:
        raise NotImplementedError


class DeterministicJudge(Judge):
    name = "deterministic"

    def __init__(self, disabled: Iterable[str] = ()) -> None:
        self.disabled = frozenset(disabled)

    def grade(
        self, question: str, answer: str, *, boundary: str = "", asof: Optional[date] = None
    ) -> RubricResult:
        signals = detect_signals(
            question, answer, boundary=boundary, asof=asof, disabled=self.disabled
        )
        dims = {name: PASS for name in DIMENSION_NAMES}
        declined = is_decline(answer)
        if not declined:
            dims["honest_absence"] = NA
        for sig in signals:
            dims[sig.dimension] = FAIL
        if signals:
            verdict = WEIRD
            reason = signals[0].evidence
            confidence = "high" if len(signals) > 1 else "med"
        elif declined:
            verdict = GOOD_DECLINE
            reason = "states an absence with no detected defect; whether the absence is true is not checkable offline"
            confidence = "low"
        else:
            verdict = GOOD_ANSWER
            reason = "answers the question with no detected defect"
            confidence = "low"
        return RubricResult(verdict, dims, reason, signals, judge=self.name, confidence=confidence)


# ─────────────────────────────────────────────────────────────────────────────────────────
# LLM backend -- structured output, validated, never guessed
# ─────────────────────────────────────────────────────────────────────────────────────────

JUDGE_SCHEMA: Dict[str, object] = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": list(VERDICTS)},
        "dimensions": {
            "type": "object",
            "properties": {
                name: {"type": "string", "enum": [PASS, FAIL, NA]} for name in DIMENSION_NAMES
            },
            "required": list(DIMENSION_NAMES),
        },
        "reason": {"type": "string"},
    },
    "required": ["verdict", "dimensions", "reason"],
}

_JUDGE_SYSTEM = """You grade one recorded answer from a building assistant. You are not the
assistant and you never answer the question yourself. You judge only the recorded text.

Score these five dimensions, each PASS, FAIL or NA:
- answers_question: does it answer what was asked, rather than apologise, return a template,
  name its own internal machinery, tell the reader to add or upload data, or ask the reader
  to narrow a question that cannot be narrowed?
- figures_traceable: is every figure it states traceable to something the answer itself
  names (a row, a record id, a named register)? A stated part larger than its whole, a
  breakdown that does not add up, or a past date offered as the next one, is FAIL.
- honest_absence: if it says something is absent, is the absence stated honestly and about
  the thing that was asked? Attributing the building's data to the reader ("the records you
  have", "the ontology you provided") is FAIL. NA when it states no absence.
- no_invented_claim: is it free of conclusions the evidence it cites cannot support?
- right_subject: is the whole answer, including any footer, about the subject asked about?
  A decline that reports statistics from an unrelated register is FAIL.

Then give one verdict:
- GOOD_ANSWER: answers what was asked, no dimension FAIL.
- GOOD_DECLINE: an honest refusal or honest absence, about the right subject, no dimension
  FAIL. A decline is a correct answer when the building does not hold the thing asked for.
- WEIRD: would read as broken, off-topic, incomplete, invented, or as an instruction to add
  data. Any dimension FAIL means WEIRD.

Reply with one JSON object and nothing else."""


class LLMJudge(Judge):
    """Structured-output judge. An unparseable or schema-invalid reply is UNGRADED."""

    name = "llm"

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: float = 180.0,
        max_answer_chars: int = 6000,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434"
        ).rstrip("/")
        self.model = (
            model
            or os.environ.get("RUBRIC_JUDGE_MODEL")
            or os.environ.get("LOCAL_MODEL")
            or "gpt-oss:20b"
        )
        self.timeout = timeout
        self.max_answer_chars = max_answer_chars
        self.calls = 0
        self.failures = 0

    # -- transport ------------------------------------------------------------------
    def _post(self, payload: Dict[str, object]) -> Dict[str, object]:
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _prompt(self, question: str, answer: str, boundary: str) -> str:
        ans = normalise(answer)
        if len(ans) > self.max_answer_chars:
            ans = ans[: self.max_answer_chars] + "\n[...answer truncated for grading...]"
        parts = [f"QUESTION ASKED:\n{question.strip()}"]
        if boundary.strip():
            parts.append(f"\nANSWER BOUNDARY the question carries:\n{boundary.strip()}")
        parts.append(f"\nRECORDED ANSWER:\n{ans}")
        return "\n".join(parts)

    # -- validation -----------------------------------------------------------------
    @staticmethod
    def validate(obj: object) -> Optional[RubricResult]:
        """Return a RubricResult only when the object satisfies JUDGE_SCHEMA."""
        if not isinstance(obj, dict):
            return None
        verdict = obj.get("verdict")
        dims = obj.get("dimensions")
        reason = obj.get("reason")
        if verdict not in VERDICTS or not isinstance(dims, dict) or not isinstance(reason, str):
            return None
        clean: Dict[str, str] = {}
        for name in DIMENSION_NAMES:
            value = dims.get(name)
            if value not in (PASS, FAIL, NA):
                return None
            clean[name] = value
        return RubricResult(verdict, clean, reason.strip()[:300], [], judge="llm", confidence="med")

    def grade(
        self, question: str, answer: str, *, boundary: str = "", asof: Optional[date] = None
    ) -> RubricResult:
        payload = {
            "model": self.model,
            "stream": False,
            "format": JUDGE_SCHEMA,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": self._prompt(question, answer, boundary)},
            ],
        }
        self.calls += 1
        try:
            raw = self._post(payload)
            content = (raw.get("message") or {}).get("content") or ""
            parsed = json.loads(content)
        except (urllib.error.URLError, OSError, json.JSONDecodeError, TypeError) as exc:
            self.failures += 1
            return RubricResult(
                UNGRADED,
                {n: NA for n in DIMENSION_NAMES},
                f"judge reply unusable: {type(exc).__name__}",
                [],
                judge=self.name,
                confidence="none",
            )
        result = self.validate(parsed)
        if result is None:
            self.failures += 1
            return RubricResult(
                UNGRADED,
                {n: NA for n in DIMENSION_NAMES},
                "judge reply did not satisfy the schema",
                [],
                judge=self.name,
                confidence="none",
            )
        return result


def make_judge(name: str, **kwargs) -> Judge:
    if name == "deterministic":
        return DeterministicJudge()
    if name == "llm":
        return LLMJudge(**kwargs)
    raise ValueError(f"unknown judge: {name!r}")


# ─────────────────────────────────────────────────────────────────────────────────────────
# Agreement statistics
# ─────────────────────────────────────────────────────────────────────────────────────────


def confusion(
    truth: Sequence[str], pred: Sequence[str], labels: Sequence[str]
) -> Dict[str, Dict[str, int]]:
    table = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(truth, pred):
        if t in table and p in table[t]:
            table[t][p] += 1
    return table


def cohen_kappa(
    truth: Sequence[str], pred: Sequence[str], labels: Sequence[str]
) -> Optional[float]:
    """Cohen's kappa. None when it is undefined (no rows, or no variance anywhere)."""
    pairs = [(t, p) for t, p in zip(truth, pred) if t in labels and p in labels]
    n = len(pairs)
    if n == 0:
        return None
    agree = sum(1 for t, p in pairs if t == p) / n
    t_counts = Counter(t for t, _ in pairs)
    p_counts = Counter(p for _, p in pairs)
    expected = sum((t_counts[l] / n) * (p_counts[l] / n) for l in labels)
    if abs(1.0 - expected) < 1e-12:
        return None
    return (agree - expected) / (1.0 - expected)


def weird_prf(truth: Sequence[str], pred: Sequence[str]) -> Dict[str, float]:
    tp = sum(1 for t, p in zip(truth, pred) if t == WEIRD and p == WEIRD)
    fp = sum(1 for t, p in zip(truth, pred) if t != WEIRD and p == WEIRD)
    fn = sum(1 for t, p in zip(truth, pred) if t == WEIRD and p != WEIRD)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1}


def accuracy(truth: Sequence[str], pred: Sequence[str]) -> float:
    if not truth:
        return 0.0
    return sum(1 for t, p in zip(truth, pred) if t == p) / len(truth)


# ─────────────────────────────────────────────────────────────────────────────────────────
# Corpus loading
# ─────────────────────────────────────────────────────────────────────────────────────────


def read_jsonl(path: Path) -> List[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


# The old heuristic's six buckets, collapsed onto the human's three.
OLD_BUCKET_TO_VERDICT = {
    "ANSWERED": GOOD_ANSWER,
    "HONEST_DECLINE": GOOD_DECLINE,
    "ADD_DATA_INSTRUCTION": WEIRD,
    "WRONG_LANE": WEIRD,
    "INCOMPLETE": WEIRD,
    "INVENTED": WEIRD,
}


@dataclass
class Split:
    name: str
    asof: date
    rows: List[dict]  # row, id, question, answer, boundary, human, old


def load_split(
    name: str, labels_path: Path, answers_path: Path, graded_path: Path, bank_path: Path, asof: date
) -> Split:
    labels = read_jsonl(labels_path)
    answers = read_jsonl(answers_path)
    graded = {g["row"]: g for g in read_jsonl(graded_path)}
    bank = {b["question"]: b for b in read_jsonl(bank_path)}
    rows = []
    for lab in labels:
        idx = lab["row"]
        ans = answers[idx]
        question = lab.get("question") or ans.get("q") or ""
        old_bucket = (graded.get(idx) or {}).get("bucket")
        rows.append(
            {
                "row": idx,
                "id": lab.get("id"),
                "question": question,
                "answer": ans.get("answer") or "",
                "boundary": (bank.get(question) or {}).get("boundary", ""),
                "human": lab["verdict"],
                "human_causes": lab.get("causes") or [],
                "human_confidence": lab.get("confidence"),
                "human_class": lab.get("defect_class") or lab.get("class"),
                "old_bucket": old_bucket,
                "old": OLD_BUCKET_TO_VERDICT.get(old_bucket, GOOD_ANSWER),
            }
        )
    return Split(name, asof, rows)


def default_splits(asof: date) -> List[Split]:
    p = REPO / "docs" / "phase0"
    return [
        load_split(
            "baseline",
            p / "phase0_read.jsonl",
            p / "phase0_baseline.md.jsonl",
            p / "phase0_graded.jsonl",
            p / "phase0_bank.jsonl",
            asof,
        ),
        load_split(
            "rerun",
            p / "phase0_rerun_read.jsonl",
            p / "phase0_rerun.md.jsonl",
            p / "phase0_rerun_graded.jsonl",
            p / "phase0_bank.jsonl",
            asof,
        ),
    ]


# ─────────────────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────────────────


def stratified_sample(splits: Sequence[Split], n: int) -> set:
    """(split, row) keys spread evenly over the human verdicts, for a smoke-sized LLM run.

    Deterministic: same corpus, same sample, so a re-run is comparable. Taking the first n
    rows instead would sample one stakeholder group and one defect family.
    """
    by_verdict: Dict[str, List[Tuple[str, int]]] = {}
    for split in splits:
        for row in split.rows:
            by_verdict.setdefault(row["human"], []).append((split.name, row["row"]))
    for keys in by_verdict.values():
        keys.sort()
    chosen: set = set()
    order = sorted(by_verdict)
    i = 0
    while len(chosen) < n and any(by_verdict.values()):
        verdict = order[i % len(order)]
        pool = by_verdict[verdict]
        if pool:
            # even spread through the pool rather than its head
            step = max(1, len(pool) // max(1, n // len(order)))
            chosen.add(pool.pop(0))
            del pool[: step - 1]
        i += 1
        if i > 10 * n:
            break
    return chosen


def calibrate(
    splits: Sequence[Split],
    judges: Dict[str, Judge],
    llm_limit: Optional[int] = None,
    llm_keys: Optional[set] = None,
) -> dict:
    """Grade every labelled row with every judge and report agreement with the human."""
    per_row: List[dict] = []
    for split in splits:
        for i, row in enumerate(split.rows):
            entry = {
                "split": split.name,
                "row": row["row"],
                "id": row["id"],
                "question": row["question"],
                "human": row["human"],
                "human_causes": row["human_causes"],
                "human_confidence": row["human_confidence"],
                "human_class": row["human_class"],
                "old": row["old"],
                "old_bucket": row["old_bucket"],
            }
            for jname, judge in judges.items():
                if jname == "llm":
                    if llm_keys is not None and (split.name, row["row"]) not in llm_keys:
                        continue
                    if llm_keys is None and llm_limit is not None and i >= llm_limit:
                        continue
                res = judge.grade(
                    row["question"], row["answer"], boundary=row["boundary"], asof=split.asof
                )
                entry[jname] = res.verdict
                entry[f"{jname}_reason"] = res.reason
                entry[f"{jname}_dimensions"] = res.dimensions
                if res.signals:
                    entry[f"{jname}_signals"] = [s.code for s in res.signals]
            per_row.append(entry)

    return summarise(per_row, ["old"] + list(judges.keys()), [s.name for s in splits])


def summarise(per_row: List[dict], grader_names: Sequence[str], split_names: Sequence[str]) -> dict:
    """Agreement statistics from already-graded rows. No grading happens here, so a saved
    per-row file can be re-summarised without spending a single model call again."""
    grader_names = list(grader_names)

    # Rows EVERY grader scored. Comparing one grader's kappa on 294 rows with another's on a
    # 20-row sample is not a comparison: the sample has a different weird share, which moves
    # kappa on its own. The winner is decided here.
    common_keys = {
        (r["split"], r["row"])
        for r in per_row
        if all(g in r and r[g] != UNGRADED for g in grader_names)
    }
    scopes = list(split_names) + ["overall", "common"]

    stats: Dict[str, Dict[str, dict]] = {}
    for grader in grader_names:
        stats[grader] = {}
        for scope in scopes:
            if scope == "common":
                rows = [r for r in per_row if (r["split"], r["row"]) in common_keys]
            else:
                rows = [
                    r
                    for r in per_row
                    if (scope == "overall" or r["split"] == scope) and grader in r
                ]
            rows = [r for r in rows if grader in r and r[grader] != UNGRADED]
            truth = [r["human"] for r in rows]
            pred = [r[grader] for r in rows]
            b_truth = [WEIRD if t == WEIRD else "OK" for t in truth]
            b_pred = [WEIRD if p == WEIRD else "OK" for p in pred]
            stats[grader][scope] = {
                "n": len(rows),
                "ungraded": sum(
                    1
                    for r in per_row
                    if (scope == "overall" or r["split"] == scope) and r.get(grader) == UNGRADED
                ),
                "accuracy": accuracy(truth, pred),
                "kappa_3class": cohen_kappa(truth, pred, VERDICTS),
                "kappa_weird": cohen_kappa(b_truth, b_pred, (WEIRD, "OK")),
                "weird": weird_prf(truth, pred),
                "confusion": confusion(truth, pred, VERDICTS),
                "predicted_weird_share": (
                    (sum(1 for p in pred if p == WEIRD) / len(pred)) if pred else 0.0
                ),
                "human_weird_share": (
                    (sum(1 for t in truth if t == WEIRD) / len(truth)) if truth else 0.0
                ),
            }
    return {"rows": per_row, "stats": stats, "graders": grader_names, "common_n": len(common_keys)}


SIGNAL_CODES = (
    "ADD_DATA_INSTRUCTION",
    "USER_ATTRIBUTION",
    "PROVENANCE_LEAK",
    "LANE_JARGON",
    "NON_ANSWER_TEMPLATE",
    "FOOTER_MISFIRE",
    "INTERNAL_TOKEN",
    "REPETITION",
    "FRAGMENT",
    "COUNT_CONTRADICTION",
    "BREAKDOWN_SUM",
    "TABLE_COUNT_MISMATCH",
    "DOCUMENT_CATCHALL",
    "ONTOLOGY_NAMED",
    "PHRASE_NOT_A_PLACE",
    "DEICTIC_BOUND",
    "STALE_FUTURE_DATE",
    "UNRELATED_REGISTER",
    "OPEN_DOMAIN_PROSE",
)


def signal_ablation(splits: Sequence[Split]) -> List[dict]:
    """For every rule: how often it fires on a human-weird row, on a human-good row, and
    what the deterministic kappa becomes without it. A rule that does not pay is visible."""
    full = DeterministicJudge()
    graded = []
    for split in splits:
        for row in split.rows:
            res = full.grade(
                row["question"], row["answer"], boundary=row["boundary"], asof=split.asof
            )
            graded.append((split, row, {s.code for s in res.signals}))

    truth = [row["human"] for _, row, _ in graded]
    b_truth = [WEIRD if t == WEIRD else "OK" for t in truth]
    base_pred = [
        WEIRD if codes else (GOOD_DECLINE if is_decline(row["answer"]) else GOOD_ANSWER)
        for _, row, codes in graded
    ]
    base_kappa = cohen_kappa(
        b_truth, [WEIRD if p == WEIRD else "OK" for p in base_pred], (WEIRD, "OK")
    )

    out = []
    for code in SIGNAL_CODES:
        fires_weird = sum(1 for _, row, codes in graded if code in codes and row["human"] == WEIRD)
        fires_good = sum(1 for _, row, codes in graded if code in codes and row["human"] != WEIRD)
        judge = DeterministicJudge(disabled={code})
        pred = []
        for split, row, _ in graded:
            pred.append(
                judge.grade(
                    row["question"], row["answer"], boundary=row["boundary"], asof=split.asof
                ).verdict
            )
        k = cohen_kappa(b_truth, [WEIRD if p == WEIRD else "OK" for p in pred], (WEIRD, "OK"))
        out.append(
            {
                "code": code,
                "fires_on_weird": fires_weird,
                "fires_on_good": fires_good,
                "kappa_without": k,
                "kappa_delta": (
                    (base_kappa - k) if (k is not None and base_kappa is not None) else None
                ),
            }
        )
    out.sort(key=lambda r: (r["kappa_delta"] if r["kappa_delta"] is not None else -9), reverse=True)
    return out


# ─────────────────────────────────────────────────────────────────────────────────────────
# Grading a recorded run, and the regression gate
# ─────────────────────────────────────────────────────────────────────────────────────────


def grade_run(
    path: Path, judge: Judge, bank: Optional[Path] = None, asof: Optional[date] = None
) -> List[dict]:
    """Grade a recorded run file (`ask_questions.py --out` .md.jsonl). Never asks the system."""
    answers = read_jsonl(path)
    boundaries: Dict[str, str] = {}
    if bank and bank.exists():
        boundaries = {b["question"]: b.get("boundary", "") for b in read_jsonl(bank)}
    out = []
    for i, rec in enumerate(answers):
        question = rec.get("q") or rec.get("question") or ""
        answer = rec.get("answer") or ""
        res = judge.grade(question, answer, boundary=boundaries.get(question, ""), asof=asof)
        out.append(
            {
                "row": i,
                "question": question,
                "status": rec.get("status"),
                "secs": rec.get("secs"),
                **res.as_dict(),
            }
        )
    return out


def weird_share(graded: Sequence[dict]) -> float:
    scored = [g for g in graded if g["verdict"] != UNGRADED]
    if not scored:
        return 0.0
    return sum(1 for g in scored if g["verdict"] == WEIRD) / len(scored)


def gate(new_graded: Sequence[dict], old_graded: Sequence[dict]) -> Tuple[bool, dict]:
    """Compare two graded runs. Returns (ok, detail); ok is False when weird share rises."""
    old_by_q = {g["question"]: g for g in old_graded}
    improved, regressed = [], []
    for g in new_graded:
        prev = old_by_q.get(g["question"])
        if not prev or UNGRADED in (g["verdict"], prev["verdict"]):
            continue
        if prev["verdict"] == WEIRD and g["verdict"] != WEIRD:
            improved.append((g["question"], prev["verdict"], g["verdict"], g["reason"]))
        elif prev["verdict"] != WEIRD and g["verdict"] == WEIRD:
            regressed.append((g["question"], prev["verdict"], g["verdict"], g["reason"]))
    new_share, old_share = weird_share(new_graded), weird_share(old_graded)
    detail = {
        "new_weird_share": new_share,
        "baseline_weird_share": old_share,
        "delta": new_share - old_share,
        "improved": improved,
        "regressed": regressed,
        "compared": len([g for g in new_graded if g["question"] in old_by_q]),
    }
    return (new_share <= old_share + 1e-9), detail


# ─────────────────────────────────────────────────────────────────────────────────────────
# Reporting
# ─────────────────────────────────────────────────────────────────────────────────────────


def _fmt_kappa(value: Optional[float]) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def ablation_markdown(rows: Sequence[dict]) -> str:
    lines = [
        "",
        "## What each deterministic rule is worth",
        "",
        "`kappa without` is the deterministic judge's weird/not kappa with that one rule removed.",
        "A rule with a negative delta costs more than it earns.",
        "",
        "| rule | fires on human-WEIRD | fires on human-GOOD | kappa without | delta |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in rows:
        delta = "n/a" if r["kappa_delta"] is None else f"{r['kappa_delta']:+.3f}"
        lines.append(
            f"| {r['code']} | {r['fires_on_weird']} | {r['fires_on_good']} | {_fmt_kappa(r['kappa_without'])} | {delta} |"
        )
    return "\n".join(lines) + "\n"


def calibration_markdown(
    result: dict, *, llm_limit: Optional[int], asof: date, llm_sampled: bool = False
) -> str:
    stats = result["stats"]
    graders = result["graders"]
    lines: List[str] = []
    lines.append("# Grader calibration against human labels")
    lines.append("")
    lines.append(f"- as-of date used for date checks: `{asof.isoformat()}`")
    lines.append(f"- graders compared: {', '.join('`' + g + '`' for g in graders)}")
    if llm_limit is not None and "llm" in graders:
        where = (
            f"a verdict-stratified sample of {llm_limit} rows drawn across both splits"
            if llm_sampled
            else f"the first {llm_limit} rows of each split"
        )
        lines.append(
            f"- **the LLM judge ran on {where} only (smoke size).** Its numbers are indicative; "
            "full calibration over all 294 rows is owed and needs a GPU slot."
        )
    lines.append("")
    lines.append("## Agreement with the human labels")
    lines.append("")
    lines.append(
        "`common` is the row set every grader scored; it is the only scope on which the graders "
        "can be ranked against each other."
    )
    lines.append("")
    lines.append(
        "| grader | split | n | accuracy | kappa (3-class) | kappa (weird / not) | weird P | weird R | weird F1 | predicted weird share |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for grader in graders:
        for scope, s in stats[grader].items():
            w = s["weird"]
            lines.append(
                f"| {grader} | {scope} | {s['n']} | {s['accuracy']:.1%} | {_fmt_kappa(s['kappa_3class'])} | "
                f"{_fmt_kappa(s['kappa_weird'])} | {w['precision']:.1%} | {w['recall']:.1%} | {w['f1']:.1%} | "
                f"{s['predicted_weird_share']:.1%} |"
            )
    lines.append("")
    lines.append("## Confusion matrices (rows = human, columns = grader)")
    for grader in graders:
        for scope, s in stats[grader].items():
            if scope != "overall":
                continue
            lines.append("")
            lines.append(f"### {grader} (overall, n={s['n']})")
            lines.append("")
            lines.append("| human \\ grader | " + " | ".join(VERDICTS) + " |")
            lines.append("|---|" + "---:|" * len(VERDICTS))
            for t in VERDICTS:
                lines.append(
                    f"| {t} | " + " | ".join(str(s["confusion"][t][p]) for p in VERDICTS) + " |"
                )
    return "\n".join(lines) + "\n"


def write_outputs(prefix: Path, result: dict, markdown: str) -> None:
    prefix.parent.mkdir(parents=True, exist_ok=True)
    prefix.with_suffix(".json").write_text(
        json.dumps(
            {
                "stats": result["stats"],
                "graders": result["graders"],
                "ablation": result.get("ablation", []),
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    prefix.with_name(prefix.name + "_rows").with_suffix(".jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in result["rows"]) + "\n",
        encoding="utf-8",
    )
    prefix.with_suffix(".md").write_text(markdown, encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────────────────


def _parse_date(text: Optional[str]) -> Optional[date]:
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--calibrate", action="store_true", help="measure every grader against the human labels"
    )
    mode.add_argument("--grade", metavar="RUN_JSONL", help="grade one recorded run")
    mode.add_argument(
        "--gate", metavar="RUN_JSONL", help="grade a run and compare it with --baseline"
    )
    mode.add_argument(
        "--recompute",
        metavar="ROWS_JSONL",
        help="re-summarise a saved calibration _rows.jsonl (no grading, no model calls)",
    )
    ap.add_argument("--baseline", metavar="RUN_JSONL", help="the previous recorded run, for --gate")
    ap.add_argument("--judge", default="deterministic", choices=["deterministic", "llm"])
    ap.add_argument("--with-llm", action="store_true", help="add the LLM judge to --calibrate")
    ap.add_argument(
        "--llm-limit", type=int, default=20, help="rows per split for the LLM judge (default 20)"
    )
    ap.add_argument(
        "--llm-sample",
        type=int,
        help="grade a verdict-stratified sample of N rows across both splits",
    )
    ap.add_argument(
        "--llm-all",
        action="store_true",
        help="run the LLM judge over every labelled row (needs a GPU slot)",
    )
    ap.add_argument("--bank", default="docs/phase0/phase0_bank.jsonl")
    ap.add_argument("--asof", help="YYYY-MM-DD the run was recorded; enables the stale-date check")
    ap.add_argument("--out", help="output prefix (writes .md, .json and _rows.jsonl)")
    ap.add_argument("--no-ablation", action="store_true", help="skip the per-rule ablation table")
    ap.add_argument("--quiet", action="store_true")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    asof = _parse_date(args.asof) or date.today()

    if args.calibrate:
        judges: Dict[str, Judge] = {"deterministic": DeterministicJudge()}
        limit = None
        splits = default_splits(asof)
        keys = None
        if args.with_llm:
            judges["llm"] = LLMJudge()
            if args.llm_all:
                limit = None
            elif args.llm_sample:
                keys = stratified_sample(splits, args.llm_sample)
                limit = args.llm_sample
            else:
                limit = args.llm_limit
        result = calibrate(splits, judges, llm_limit=limit, llm_keys=keys)
        md = calibration_markdown(result, llm_limit=limit, asof=asof, llm_sampled=keys is not None)
        if not args.no_ablation:
            result["ablation"] = signal_ablation(splits)
            md += ablation_markdown(result["ablation"])
        if not args.quiet:
            print(md)
        if args.out:
            write_outputs(Path(args.out), result, md)
            print(f"wrote {args.out}.md / .json / _rows.jsonl")
        # Say plainly which grader wins, and by how much -- judged only on rows every grader
        # scored, and reported as provisional when that set is a sample.
        scope = "common"
        n_common = result.get("common_n", 0)
        best = max(
            result["graders"],
            key=lambda g: (result["stats"][g][scope]["kappa_weird"] or -1.0),
        )
        old_k = result["stats"]["old"][scope]["kappa_weird"] or 0.0
        best_k = result["stats"][best][scope]["kappa_weird"] or 0.0
        print(f"\nVERDICT (on the {n_common} rows every grader scored):")
        if best == "old":
            print("  No new grader beats the old heuristic on this row set. NOT adopted.")
        else:
            print(
                f"  '{best}' wins on the weird class: kappa {best_k:.3f} vs the old "
                f"heuristic's {old_k:.3f} (+{best_k - old_k:.3f})."
            )
        if n_common < sum(len(s.rows) for s in splits):
            print(
                f"  This row set is a {n_common}-row sample, not the corpus. Its weird share "
                "differs from the corpus's, which moves kappa on its own -- treat it as\n"
                "  provisional and re-run over all rows before adopting anything."
            )
            det = result["stats"].get("deterministic", {}).get("overall")
            if det:
                print(
                    f"  On all 294 rows the deterministic judge scores kappa "
                    f"{det['kappa_weird']:.3f} against the old heuristic's "
                    f"{result['stats']['old']['overall']['kappa_weird']:.3f}."
                )
        return 0

    if args.recompute:
        per_row = read_jsonl(Path(args.recompute))
        graders = ["old"] + [g for g in ("deterministic", "llm") if any(g in r for r in per_row)]
        splits_seen = sorted({r["split"] for r in per_row})
        result = summarise(per_row, graders, splits_seen)
        result["rows"] = per_row
        llm_n = sum(1 for r in per_row if "llm" in r)
        md = calibration_markdown(
            result,
            llm_limit=llm_n if ("llm" in graders and llm_n < len(per_row)) else None,
            asof=asof,
            llm_sampled=True,
        )
        print(md)
        if args.out:
            write_outputs(Path(args.out), result, md)
            print(f"wrote {args.out}.md / .json / _rows.jsonl")
        return 0

    judge = make_judge(args.judge)

    if args.grade:
        graded = grade_run(Path(args.grade), judge, bank=Path(args.bank), asof=asof)
        counts = Counter(g["verdict"] for g in graded)
        if args.out:
            prefix = Path(args.out)
            prefix.parent.mkdir(parents=True, exist_ok=True)
            prefix.with_suffix(".jsonl").write_text(
                "\n".join(json.dumps(g, ensure_ascii=False) for g in graded) + "\n",
                encoding="utf-8",
            )
            print(f"wrote {prefix.with_suffix('.jsonl')}")
        for verdict in VERDICTS + (UNGRADED,):
            if counts.get(verdict):
                print(f"{verdict:<14} {counts[verdict]:>4}")
        print(f"weird share: {weird_share(graded):.1%}")
        return 0

    if args.gate:
        if not args.baseline:
            print("--gate requires --baseline", file=sys.stderr)
            return 2
        new_graded = grade_run(Path(args.gate), judge, bank=Path(args.bank), asof=asof)
        old_graded = grade_run(Path(args.baseline), judge, bank=Path(args.bank), asof=asof)
        ok, detail = gate(new_graded, old_graded)
        print(f"compared {detail['compared']} questions present in both runs")
        print(f"baseline weird share: {detail['baseline_weird_share']:.1%}")
        print(f"new weird share:      {detail['new_weird_share']:.1%}  ({detail['delta']:+.1%})")
        print(f"\nimproved ({len(detail['improved'])}):")
        for q, before, after, why in detail["improved"][:40]:
            print(f"  + {before} -> {after}  {q[:70]}")
        print(f"\nregressed ({len(detail['regressed'])}):")
        for q, before, after, why in detail["regressed"][:40]:
            print(f"  - {before} -> {after}  {q[:70]}\n      {why[:110]}")
        if not ok:
            print("\nGATE FAILED: the weird share rose.")
            return 1
        print("\nGATE PASSED.")
        return 0

    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
